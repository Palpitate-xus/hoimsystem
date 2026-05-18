import os, re
from collections import defaultdict

views_dir = '/home/xusheng/workspace/hoimsystem/vue3-new-ui/src/views'
issues = []

for root, dirs, files in os.walk(views_dir):
    if 'vab' in root:
        continue
    for f in files:
        if not f.endswith('.vue'):
            continue
        path = os.path.join(root, f)
        rel = path.replace(views_dir + '/', '')
        content = open(path, encoding='utf-8').read()

        # Check for el-table without empty-text
        if 'el-table' in content and 'empty-text' not in content:
            issues.append(('missing_empty_text', rel, ''))

        # Check for .then without .catch
        then_count = len(re.findall(r'\.then\s*\(', content))
        catch_count = len(re.findall(r'\.catch\s*\(', content))
        if then_count > 0 and catch_count == 0:
            issues.append(('missing_catch', rel, f'then={then_count}, catch=0'))

        # Check for hardcoded English in templates
        for m in re.finditer(r'>([A-Z][a-zA-Z\s]{2,30})<', content):
            text = m.group(1).strip()
            if text and not any('一' <= c <= '鿿' for c in text):
                line_start = content.rfind('\n', 0, m.start())
                line = content[line_start:m.start()+len(text)+2]
                if '{{' not in line and ':title' not in line and 'v-' not in line:
                    issues.append(('english_text', rel, text))

        # Check for English placeholder text
        for m in re.finditer(r'placeholder="([a-zA-Z][a-zA-Z\s,\.]{2,}?)"', content):
            text = m.group(1)
            if not any('一' <= c <= '鿿' for c in text):
                issues.append(('english_placeholder', rel, text))

        # Check for English in ElMessage hardcoded strings
        for m in re.finditer(r'ElMessage\.(error|success|warning|info)\s*\(\s*["\']([a-zA-Z][a-zA-Z\s,\.!]{2,}?)["\']', content):
            issues.append(('english_message', rel, m.group(2)))

        # Check for console statements
        console_matches = re.findall(r'console\.(log|error|warn|info)\s*\(', content)
        if console_matches:
            issues.append(('console', rel, f'{len(console_matches)} statements'))

print('=== 前端页面代码分析结果 ===')
print(f'总问题数: {len(issues)}')
print()

by_type = defaultdict(list)
for typ, file, detail in issues:
    by_type[typ].append((file, detail))

for typ, items in sorted(by_type.items(), key=lambda x: -len(x[1])):
    print(f'\n【{typ}】共 {len(items)} 处')
    seen = set()
    for file, detail in items[:15]:
        key = f'{file}:{detail}'
        if key not in seen:
            seen.add(key)
            print(f'  - {file}: {detail}')
    if len(items) > 15:
        print(f'  ... 等共 {len(items)} 处')

# Also check for specific patterns
print('\n\n=== 详细检查 ===')

# Check all pages for Element Plus default texts
print('\n【Element Plus 默认文本检查】')
for root, dirs, files in os.walk(views_dir):
    if 'vab' in root:
        continue
    for f in files:
        if not f.endswith('.vue'):
            continue
        path = os.path.join(root, f)
        rel = path.replace(views_dir + '/', '')
        content = open(path, encoding='utf-8').read()
        # Check for pagination without layout text
        if 'el-pagination' in content:
            if 'layout' not in content or ('prev' in content and 'pager' in content):
                pass  # OK, has layout
        # Check for default el-table empty
        if 'el-table' in content and 'empty-text' not in content:
            print(f'  - {rel}: el-table 缺少 empty-text，将显示默认英文 "No Data"')
