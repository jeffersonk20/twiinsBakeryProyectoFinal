import os

files = [
    'html/dashboard_admin.html',
    'html/admin_reservas.html',
    'html/admin_nueva_reserva.html',
    'html/admin_agr_producto.html',
    'html/admin_chat.html',
    'html/admin_configuracion.html',
    'html/admin_eventos.html',
    'html/admin_fidelidad.html',
    'html/admin_fidelidad_canjes.html',
    'html/admin_fidelidad_configuracion.html',
    'html/admin_fidelidad_historial.html'
]

link_to_insert = '<a href="{{ url_for(\'admin_ingresos\') }}">Ingresos</a>'

for path in files:
    with open(path, 'r', encoding='utf-8') as f:
        content = f.read()

    if link_to_insert in content:
        print(f"Already updated: {path}")
        continue

    # Search for the Reservas nav link in the sidebar
    patterns = [
        '<a class="active active-tab" href="{{ url_for(\'admin_reservas\') }}">Reservas</a>',
        '<a href="{{ url_for(\'admin_reservas\') }}">Reservas</a>'
    ]

    updated = False
    for p in patterns:
        if p in content:
            # We want to replace only the first occurrence (which is in the sidebar nav)
            # Find indentation
            idx = content.find(p)
            # Find leading whitespace on that line
            line_start = content.rfind('\n', 0, idx) + 1
            indent = content[line_start:idx]
            replacement = p + '\n' + indent + link_to_insert
            content = content[:idx] + replacement + content[idx + len(p):]
            updated = True
            break

    if updated:
        with open(path, 'w', encoding='utf-8') as f:
            f.write(content)
        print(f"Successfully updated: {path}")
    else:
        print(f"Pattern not found in: {path}")
