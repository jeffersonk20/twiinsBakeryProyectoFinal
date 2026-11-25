import glob
import re

pattern = re.compile(r'\s*<!-- Modal [^\n]*cierre de sesión[^\n]*-->\s*<div class="custom-modal-overlay" id="logoutModal"[\s\S]*?</div>\s*</div>', re.IGNORECASE)

files = glob.glob('html/*.html')
count = 0
for f in files:
    with open(f, 'r', encoding='utf-8') as fh:
        content = fh.read()
    new_content, n = pattern.subn('', content)
    if n > 0:
        with open(f, 'w', encoding='utf-8') as fh:
            fh.write(new_content)
        print(f"Modificado: {f} ({n} ocurrencias)")
        count += n

print(f"Total eliminados: {count}")
