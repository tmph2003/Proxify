import glob
import re

for f in glob.glob('c:/Users/Administrator/Desktop/MyAim/Proxify/proxify/ui/frontend/src/pages/*.tsx'):
    with open(f, 'r', encoding='utf-8') as file:
        content = file.read()
    
    # Strip event handlers completely
    content = re.sub(r'\s+on[A-Z][a-zA-Z]+="[^"]*"', '', content)
    content = re.sub(r'\s+on[a-z]+="[^"]*"', '', content)
    
    # Fix boolean attributes
    content = content.replace('checked="true"', 'defaultChecked={true}')
    content = content.replace('checked="checked"', 'defaultChecked={true}')
    content = content.replace('checked=""', 'defaultChecked={true}')
    
    # Fix duplicate padding in Zalo.tsx
    content = re.sub(r"'padding': '[^']+', 'padding': '[^']+'", "'padding': '16px'", content)
    
    with open(f, 'w', encoding='utf-8') as file:
        file.write(content)
