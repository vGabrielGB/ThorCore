import re

VIEWS_FILE = "c:/Users/vGabrielGB/Desktop/Proyectos/agrothor/inventario/views.py"

cajero_views = [
    'dashboard_view',
    'ventas_list_view',
    'ventas_mayor_list_view',
    'venta_mayor_create_view',
    'creditos_list_view',
    'abono_credito_view',
    'venta_mayor_export_pdf_view',
    'venta_detal_create_view',
    'cierre_list_view',
    'cierre_create_view',
]

superuser_views = [
    'centro_control_view',
    'update_configuracion_view'
]

with open(VIEWS_FILE, 'r', encoding='utf-8') as f:
    lines = f.readlines()

new_lines = []
has_import = False

# Pass 1: check if already imported
for line in lines:
    if "from .decorators import cajero_gerente_required" in line:
        has_import = True
        break

for idx, line in enumerate(lines):
    if line.startswith("def "):
        match = re.match(r'^def (\w+)\(', line)
        if match:
            func_name = match.group(1)
            
            # Decide decorator
            if func_name in cajero_views:
                decorator = "@cajero_gerente_required\n"
            elif func_name in superuser_views:
                decorator = "@superuser_required\n"
            else:
                decorator = "@gerente_required\n"
            
            # Check if previous line is already a decorator to avoid double adding
            if idx > 0 and not lines[idx-1].strip().startswith("@"):
                new_lines.append(decorator)
            elif idx == 0:
                new_lines.append(decorator)
    
    new_lines.append(line)
    
    # Insert import after first imports if not exists
    if not has_import and line.startswith("from django.shortcuts import"):
        new_lines.append("from .decorators import cajero_gerente_required, gerente_required, superuser_required\n")
        has_import = True

with open(VIEWS_FILE, 'w', encoding='utf-8') as f:
    f.writelines(new_lines)

print("Decorators applied successfully.")
