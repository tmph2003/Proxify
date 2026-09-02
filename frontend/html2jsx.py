import re
import sys
from bs4 import BeautifulSoup

def style_to_object(style_str):
    if not style_str: return "{}"
    styles = []
    for prop in style_str.split(';'):
        if ':' not in prop: continue
        k, v = prop.split(':', 1)
        k = k.strip()
        # Camel case
        parts = k.split('-')
        k_camel = parts[0] + ''.join(x.title() for x in parts[1:])
        v = v.strip().replace("'", "\\'")
        styles.append(f"'{k_camel}': '{v}'")
    return "{{ " + ", ".join(styles) + " }}"

def convert_html_to_jsx(html):
    # Very rudimentary conversion
    html = html.replace('class=', 'className=')
    html = html.replace('for=', 'htmlFor=')
    html = html.replace('<!--', '{/*')
    html = html.replace('-->', '*/}')
    html = html.replace('readonly', 'readOnly')
    html = html.replace('autocomplete', 'autoComplete')
    
    # Inline styles
    def repl_style(m):
        return f"style={style_to_object(m.group(1))}"
    html = re.sub(r'style="([^"]+)"', repl_style, html)
    
    # Event handlers (rudimentary, just strip them so they don't break JSX)
    html = re.sub(r'onclick="([^"]+)"', '', html)
    html = re.sub(r'onchange="([^"]+)"', '', html)
    html = re.sub(r'onsubmit="([^"]+)"', '', html)
    
    # Self closing tags
    html = re.sub(r'<input([^>]*[^/])>', r'<input\1 />', html)
    html = re.sub(r'<img([^>]*[^/])>', r'<img\1 />', html)
    html = re.sub(r'<br([^>]*[^/])>', r'<br\1 />', html)
    html = re.sub(r'<hr([^>]*[^/])>', r'<hr\1 />', html)
    
    return html

def main():
    for name in ['facebook', 'zalo', 'index']:
        with open(f"c:/Users/Administrator/Desktop/MyAim/Proxify/proxify/ui/templates/{name}.html", "r", encoding="utf-8") as f:
            content = f.read()
        
        soup = BeautifulSoup(content, 'html.parser')
        body = soup.find('body')
        if not body: continue
        
        # Remove topbar since it's in MainLayout
        topbar = body.find('div', {'class': 'topbar'})
        if topbar: topbar.decompose()
        
        # Remove scripts
        for s in body.find_all('script'):
            s.decompose()
            
        jsx = convert_html_to_jsx(body.decode_contents())
        
        component_name = name.title() + "Page"
        if name == 'index': component_name = "DashboardPage"
        
        out = f"""import React, {{ useState, useEffect }} from 'react';

export const {component_name}: React.FC = () => {{
    return (
        <>
            {jsx}
        </>
    );
}};
"""
        with open(f"c:/Users/Administrator/Desktop/MyAim/Proxify/proxify/ui/frontend/src/pages/{component_name.replace('Page', '')}.tsx", "w", encoding="utf-8") as f:
            f.write(out)
        print(f"Generated {component_name}")

if __name__ == '__main__':
    main()
