import json
import re

transcript_path = r'C:\Users\vGabrielGB\.gemini\antigravity-ide\brain\6026cdb3-2b7f-4677-bab2-d6ac4f8a5e91\.system_generated\logs\transcript_full.jsonl'

base_content = ''

with open(transcript_path, 'r', encoding='utf-8') as f:
    lines = f.readlines()

for line in lines:
    data = json.loads(line)
    
    # 1. Capture the VIEW_FILE
    if data.get('type') == 'VIEW_FILE' and 'views.py' in data.get('content', ''):
        raw_text = data['content']
        # Extract everything after "The following code has been modified..."
        if "remove the line number, colon, and leading space." in raw_text:
            code_part = raw_text.split("remove the line number, colon, and leading space.\n")[1]
            if "The above content shows the entire, complete file contents" in code_part:
                code_part = code_part.split("The above content shows the entire, complete file contents")[0]
            
            # Remove line numbers
            clean_lines = []
            for l in code_part.split('\n'):
                # Match "number: " at the beginning
                cleaned = re.sub(r'^\d+: ', '', l)
                clean_lines.append(cleaned)
                
            base_content = '\n'.join(clean_lines).strip()

print(f'Recovered {len(base_content.split(chr(10)))} lines of base content.')

with open('views_recovered.py', 'w', encoding='utf-8') as f:
    f.write(base_content)

# Now, find edits
print('Edits made after VIEW_FILE:')
for line in lines:
    data = json.loads(line)
    if data.get('type') == 'PLANNER_RESPONSE' and 'tool_calls' in data:
        for tool in data['tool_calls']:
            if tool['name'] in ['replace_file_content', 'multi_replace_file_content']:
                if 'views.py' in tool['args'].get('TargetFile', ''):
                    print(f"--- EDIT IN STEP {data.get('step_index')} ---")
                    print(tool['name'])
                    print(tool['args'].get('Instruction'))
