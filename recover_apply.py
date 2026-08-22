import json
import re

transcript_path = r'C:\Users\vGabrielGB\.gemini\antigravity-ide\brain\6026cdb3-2b7f-4677-bab2-d6ac4f8a5e91\.system_generated\logs\transcript_full.jsonl'

with open('views_recovered.py', 'r', encoding='utf-8') as f:
    content = f.read()

with open(transcript_path, 'r', encoding='utf-8') as f:
    lines = f.readlines()

for line in lines:
    data = json.loads(line)
    if data.get('type') == 'PLANNER_RESPONSE' and 'tool_calls' in data:
        for tool in data['tool_calls']:
            if tool['name'] == 'replace_file_content' and 'views.py' in tool['args'].get('TargetFile', ''):
                target = tool['args']['TargetContent']
                replacement = tool['args']['ReplacementContent']
                if target in content:
                    content = content.replace(target, replacement)
                    print(f"Applied replace_file_content at step {data['step_index']}")
                else:
                    print(f"WARNING: target not found at step {data['step_index']}")
            
            elif tool['name'] == 'multi_replace_file_content' and 'views.py' in tool['args'].get('TargetFile', ''):
                chunks_raw = tool['args']['ReplacementChunks']
                chunks = json.loads(chunks_raw) if isinstance(chunks_raw, str) else chunks_raw
                for chunk in chunks:
                    target = chunk['TargetContent']
                    replacement = chunk['ReplacementContent']
                    if target in content:
                        content = content.replace(target, replacement)
                        print(f"Applied chunk in multi_replace_file_content at step {data['step_index']}")
                    else:
                        print(f"WARNING: chunk target not found at step {data['step_index']}")

with open(r'inventario\views.py', 'w', encoding='utf-8') as f:
    f.write(content)

print('views.py successfully reconstructed!')
