/* Bounded RFC1951 decoding for checked-in public build data only.
 * https://www.rfc-editor.org/rfc/rfc1951
 * No network, dynamic code, dictionary input, streaming or runtime patient data.
 */
var LENGTH_BASE=[3,4,5,6,7,8,9,10,11,13,15,17,19,23,27,31,35,43,51,59,67,83,99,115,131,163,195,227,258];
var LENGTH_BITS=[0,0,0,0,0,0,0,0,1,1,1,1,2,2,2,2,3,3,3,3,4,4,4,4,5,5,5,5,0];
var DISTANCE_BASE=[1,2,3,4,5,7,9,13,17,25,33,49,65,97,129,193,257,385,513,769,1025,1537,2049,3073,4097,6145,8193,12289,16385,24577];
var DISTANCE_BITS=[0,0,0,0,1,1,2,2,3,3,4,4,5,5,6,6,7,7,8,8,9,9,10,10,11,11,12,12,13,13];
var CODE_ORDER=[16,17,18,0,8,7,9,6,10,5,11,4,12,3,13,2,14,1,15];

function tree(lengths,allowEmpty){
  var counts=new Uint16Array(16),next=new Uint16Array(16),tables=[],symbols=0,last=0;
  for(var index=0;index<lengths.length;index++){
    var length=lengths[index];
    if(!Number.isInteger(length)||length<0||length>15)throw Error('Invalid static deflate code length');
    if(length){counts[length]++;symbols++;last=Math.max(last,length);}
  }
  if(!symbols){if(allowEmpty)return {tables:tables,max:0};throw Error('Empty static deflate code tree');}
  var left=1;
  for(var bits=1;bits<=15;bits++){left=left*2-counts[bits];if(left<0)throw Error('Oversubscribed static deflate tree');}
  if(left&&!(symbols===1&&last===1))throw Error('Incomplete static deflate tree');
  var code=0;
  for(var width=1;width<=15;width++){code=(code+counts[width-1])*2;next[width]=code;tables[width]=Object.create(null);}
  for(var symbol=0;symbol<lengths.length;symbol++)if(lengths[symbol])tables[lengths[symbol]][next[lengths[symbol]]++]=symbol;
  return {tables:tables,max:last};
}
var fixedLengths=new Uint8Array(288),fixedDistances=new Uint8Array(32);
for(var fixed=0;fixed<288;fixed++)fixedLengths[fixed]=fixed<144?8:fixed<256?9:fixed<280?7:8;
fixedDistances.fill(5);
var fixedLiteral=tree(fixedLengths),fixedDistance=tree(fixedDistances);

function inflateStatic(source,byteLength){
  if(!(source instanceof Uint8Array)||!source.length||!Number.isSafeInteger(byteLength)||byteLength<1||byteLength>262144||source.length>524288)throw Error('Invalid bounded static deflate bytes');
  var destination=new Uint8Array(byteLength),position=0,bitPosition=0;
  function read(width){
    if(bitPosition+width>source.length*8)throw Error('Incomplete static deflate bits');
    var value=0;
    for(var index=0;index<width;index++,bitPosition++)value|=((source[bitPosition>>>3]>>>(bitPosition&7))&1)<<index;
    return value;
  }
  function decode(value){
    var code=0;
    for(var length=1;length<=value.max;length++){
      code=code*2+read(1);
      var result=value.tables[length][code];
      if(result!==undefined)return result;
    }
    throw Error('Invalid static deflate symbol');
  }
  var final;
  do{
    final=read(1);
    var type=read(2),literal,distance;
    if(type===0){
      bitPosition=(bitPosition+7)&~7;
      var size=read(16),opposite=read(16);
      if((size^opposite)!==65535||size>destination.length-position||bitPosition+size*8>source.length*8)throw Error('Invalid complete static deflate stored block');
      destination.set(source.subarray(bitPosition>>>3,(bitPosition>>>3)+size),position);
      position+=size;bitPosition+=size*8;continue;
    }
    if(type===1){literal=fixedLiteral;distance=fixedDistance;}
    else if(type===2){
      var literalCount=read(5)+257,distanceCount=read(5)+1,codeCount=read(4)+4;
      if(literalCount>286)throw Error('Reserved static deflate literal count');
      var codeLengths=new Uint8Array(19);
      for(var count=0;count<codeCount;count++)codeLengths[CODE_ORDER[count]]=read(3);
      var codeTree=tree(codeLengths),lengths=[];
      while(lengths.length<literalCount+distanceCount){
        var item=decode(codeTree),repetitions=1,previous=item;
        if(item===16){if(!lengths.length)throw Error('Missing static deflate prior length');previous=lengths[lengths.length-1];repetitions=read(2)+3;}
        else if(item===17){previous=0;repetitions=read(3)+3;}
        else if(item===18){previous=0;repetitions=read(7)+11;}
        if(repetitions>literalCount+distanceCount-lengths.length)throw Error('Static deflate code lengths overflow');
        for(var repetition=0;repetition<repetitions;repetition++)lengths.push(previous);
      }
      if(!lengths[256])throw Error('Missing static deflate end symbol');
      literal=tree(lengths.slice(0,literalCount));distance=tree(lengths.slice(literalCount),true);
    }else throw Error('Reserved static deflate block type');
    while(true){
      var symbol=decode(literal);
      if(symbol===256)break;
      if(symbol<256){if(position===destination.length)throw Error('Static deflate literal overflow');destination[position++]=symbol;continue;}
      if(symbol>285)throw Error('Reserved static deflate length');
      var offset=symbol-257,length=LENGTH_BASE[offset]+read(LENGTH_BITS[offset]),distanceSymbol=decode(distance);
      if(distanceSymbol>29)throw Error('Reserved static deflate distance');
      var backward=DISTANCE_BASE[distanceSymbol]+read(DISTANCE_BITS[distanceSymbol]);
      if(backward>position||length>destination.length-position)throw Error('Invalid bounded static deflate reference');
      for(var copy=0;copy<length;copy++,position++)destination[position]=destination[position-backward];
    }
  }while(!final);
  if(position!==destination.length||Math.ceil(bitPosition/8)!==source.length)throw Error('Incomplete or trailing static deflate data');
  return destination;
}
module.exports={inflateStatic:inflateStatic};
