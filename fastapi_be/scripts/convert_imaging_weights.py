"""Convert the exact public legacy XRV checkpoint inside an isolated container.

Never run a pickle loader on the host. The preparation script supplies a
read-only rootfs, non-root UID, no network, no capabilities and only public
reference files plus an output mount. No downloaded source code is imported.
"""

import argparse
import collections
import hashlib
import json
import os
import pickle
import pickletools
import types
from pathlib import Path

REPOSITORY = "torchxrayvision/densenet121-res224-all"
REVISION = "588eadcc6a744da71f8dce768bc974ec629443f5"
CODE_REVISION = "17726dd8f5e756eec3e5ae958281a289b05b1dae"
WEIGHT_SHA256 = "56524913dd16a906422e8d8b66a7a5c46be1d82eb7ac012d8103776f1aa68899"
CODE_SHA256 = "3d359ee39db33ae4f9633d7cccc0756f63ad8e38b6d018776c5c2c18a0553af8"
CONFIG_SHA256 = "4b78be461c44f98af46695ce5cdbe57313e97f2e6255ac7b888e0670f368a1dd"
OUTPUT_SHA256 = "6b811edb354d83991e36a4836b914bf41faf8fb3203573c0a61820b97937c529"
SCHEMA_SHA256 = "51875470a4a913653c5eff6286ccc893907241d50a7e19857acf49bfef90b942"
ALLOWED_GLOBALS = {
    "collections.OrderedDict",
    "torch.FloatStorage",
    "torch.LongStorage",
    "torch._utils._rebuild_parameter",
    "torch._utils._rebuild_tensor_v2",
    "torch.nn.modules.activation.ReLU",
    "torch.nn.modules.batchnorm.BatchNorm2d",
    "torch.nn.modules.container.Sequential",
    "torch.nn.modules.conv.Conv2d",
    "torch.nn.modules.linear.Linear",
    "torch.nn.modules.pooling.AvgPool2d",
    "torch.nn.modules.pooling.MaxPool2d",
    "torchxrayvision.models.DenseNet",
    "torchxrayvision.models._DenseBlock",
    "torchxrayvision.models._DenseLayer",
    "torchxrayvision.models._Transition",
}


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def require_isolation():
    # These are accidental-host-execution guards. Actual Docker isolation is
    # established by prepare_local_imaging.py, before this script starts.
    if not Path("/.dockerenv").is_file() or os.getuid() == 0 or not os.statvfs("/").f_flag & os.ST_RDONLY:
        raise ValueError("Conversion requires a non-root read-only Docker container")
    status = dict(line.split(":", 1) for line in Path("/proc/self/status").read_text().splitlines() if ":" in line)
    if int(status.get("CapEff", "1").strip(), 16) != 0 or status.get("NoNewPrivs", "0").strip() != "1":
        raise ValueError("Conversion requires no capabilities and no-new-privileges")
    if {path.name for path in Path("/sys/class/net").iterdir()} != {"lo"}:
        raise ValueError("Conversion requires Docker network=none")


def scan_checkpoint(path):
    globals_seen = set()
    with path.open("rb") as stream:
        # The exact legacy serialization consists of five pickle streams,
        # followed by raw tensor storages. The entire file digest is pinned.
        for _ in range(5):
            for opcode, argument, _ in pickletools.genops(stream):
                if opcode.name in {"EXT1", "EXT2", "EXT4", "STACK_GLOBAL", "INST", "OBJ", "NEWOBJ_EX"}:
                    raise ValueError("Unexpected checkpoint opcode")
                if opcode.name == "GLOBAL":
                    module, name = argument.split(" ", 1)
                    globals_seen.add(module + "." + name)
    if globals_seen != ALLOWED_GLOBALS:
        raise ValueError("Checkpoint globals differ from the reviewed exact allowlist")
    return globals_seen


def convert(reference, output):
    require_isolation()
    reference, output = Path(reference), Path(output)
    for name, size, expected in (
        ("model.pt", 28382008, WEIGHT_SHA256),
        ("models.py", 25374, CODE_SHA256),
        ("config.json", 1158, CONFIG_SHA256),
    ):
        path = reference / name
        if path.is_symlink() or not path.is_file() or path.stat().st_size != size or digest(path) != expected:
            raise ValueError("Public reference bytes differ from the reviewed release")
    seen = scan_checkpoint(reference / "model.pt")
    import safetensors
    import torch
    from safetensors.torch import load_file, save_file

    if torch.__version__ not in {"2.14.1+cpu", "2.15.0+cpu"} or safetensors.__version__ != "0.8.0":
        raise ValueError("Conversion requires pinned CPU torch and safetensors versions")
    torch.set_num_threads(4)
    allowed = {}
    for name in ("DenseNet", "_DenseLayer", "_DenseBlock", "_Transition"):
        # No source class, constructor, forward or serialization method runs.
        allowed["torchxrayvision.models." + name] = type(name, (torch.nn.Module,), {"__module__": "hoim_conversion_stubs"})
    for cls in (torch.nn.Sequential, torch.nn.Conv2d, torch.nn.BatchNorm2d, torch.nn.ReLU, torch.nn.MaxPool2d, torch.nn.AvgPool2d, torch.nn.Linear):
        allowed[cls.__module__ + "." + cls.__name__] = cls
    allowed.update(
        {
            "collections.OrderedDict": collections.OrderedDict,
            "torch.FloatStorage": torch.FloatStorage,
            "torch.LongStorage": torch.LongStorage,
            "torch._utils._rebuild_parameter": torch._utils._rebuild_parameter,
            "torch._utils._rebuild_tensor_v2": torch._utils._rebuild_tensor_v2,
        }
    )
    if set(allowed) != ALLOWED_GLOBALS:
        raise ValueError("Converter's actual globals differ from the fixed allowlist")

    class RestrictedUnpickler(pickle.Unpickler):
        def find_class(self, module, name):
            qualified = module + "." + name
            if qualified not in allowed:
                raise pickle.UnpicklingError("Rejected pickle global: " + qualified)
            return allowed[qualified]

    restricted_pickle = types.ModuleType("hoim_restricted_pickle")
    restricted_pickle.Unpickler = RestrictedUnpickler
    restricted_pickle.load = lambda stream, **kwargs: RestrictedUnpickler(stream, **kwargs).load()
    # weights_only=True cannot read this exact legacy format: its module
    # persistent IDs are rejected before persistent_load. This restrictive
    # pickle module is the sole loader; there is no unrestricted fallback.
    recovered = torch.load(reference / "model.pt", map_location="cpu", weights_only=False, pickle_module=restricted_pickle)
    if not isinstance(recovered, torch.nn.Module):
        raise ValueError("Checkpoint did not recover a module-shaped tensor mapping")
    state = collections.OrderedDict()
    for key, value in recovered.state_dict().items():
        if not isinstance(key, str) or not isinstance(value, torch.Tensor) or not torch.isfinite(value).all().item():
            raise ValueError("Invalid checkpoint tensor")
        state[key] = value.detach().cpu().contiguous().clone()
    schema = [{"key": key, "dtype": str(value.dtype), "shape": list(value.shape)} for key, value in sorted(state.items())]
    schema_hash = hashlib.sha256(json.dumps(schema, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    if len(state) != 727 or schema_hash != SCHEMA_SHA256:
        raise ValueError("Checkpoint tensor keys, types or shapes differ from the reviewed architecture")
    labels = json.loads((reference / "config.json").read_text())["labels"]
    provenance = {
        "format": "pt",
        "source_model": REPOSITORY,
        "source_revision": REVISION,
        "source_sha256": WEIGHT_SHA256,
        "architecture_code_revision": CODE_REVISION,
        "architecture_code_sha256": CODE_SHA256,
        "conversion": "isolated restricted Unpickler with exact 16-global allowlist and inert nn.Module stubs",
        "labels": labels,
    }
    metadata = {"hoim_provenance": json.dumps(provenance, sort_keys=True, separators=(",", ":"))}
    output.mkdir(exist_ok=True)
    target, repeat = output / "model.safetensors", output / "repeat.safetensors"
    if target.exists() or repeat.exists():
        raise ValueError("Conversion output already exists")
    save_file(state, target, metadata=metadata)
    save_file(state, repeat, metadata=metadata)
    if target.stat().st_size != 28283736 or digest(target) != OUTPUT_SHA256 or digest(repeat) != OUTPUT_SHA256:
        raise ValueError("Conversion bytes differ from the reviewed deterministic safetensors")
    repeat.unlink()
    # Public reviewed weights must be readable by the host-side staging UID;
    # safetensors otherwise creates a private file owned by container UID 10001.
    target.chmod(0o644)
    restored = load_file(target, device="cpu")
    if set(restored) != set(state) or not all(torch.equal(state[key], restored[key]) for key in state):
        raise ValueError("Safetensors roundtrip changed a tensor")
    report = {
        "source_sha256": WEIGHT_SHA256,
        "output_sha256": OUTPUT_SHA256,
        "output_bytes": target.stat().st_size,
        "tensor_count": len(state),
        "state_schema_sha256": schema_hash,
        "allowlisted_globals": sorted(seen),
        "all_tensor_bytes_roundtrip_equal": True,
        "repeated_serialization_equal": True,
        "source_code_imported_during_deserialization": False,
        "clinical_validation": False,
    }
    print(json.dumps(report, sort_keys=True))
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference", default="/reference")
    parser.add_argument("--output", default="/output")
    args = parser.parse_args()
    convert(args.reference, args.output)


if __name__ == "__main__":
    main()
