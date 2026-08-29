import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from django.contrib.auth.models import Group, Permission
from django.contrib.contenttypes.models import ContentType

def setup_roles():
    print("Iniciando configuración de roles y permisos...")
    
    # Asegurar que los grupos existen
    cajero_group, _ = Group.objects.get_or_create(name='Cajero')
    gerente_group, _ = Group.objects.get_or_create(name='Gerente')

    # Limpiar permisos previos
    cajero_group.permissions.clear()
    gerente_group.permissions.clear()

    # Modelos del Cajero
    cajero_models = [
        'ventadetal', 'detalleventadetal',
        'ventamayor', 'detalleventamayor',
        'cierrediario', 'detallecierrediario',
        'credito', 'abonocredito'
    ]

    # Modelos excluidos para el Gerente
    gerente_excluded_models = ['configuracionnegocio']

    # Obtener todos los permisos del app 'inventario'
    inventario_permissions = Permission.objects.filter(content_type__app_label='inventario')

    for perm in inventario_permissions:
        model_name = perm.content_type.model
        
        # Permisos para el Cajero (agregar, cambiar, ver)
        if model_name in cajero_models:
            cajero_group.permissions.add(perm)
            
        # Permisos para el Gerente (todos menos la configuración)
        if model_name not in gerente_excluded_models:
            gerente_group.permissions.add(perm)

    print("Permisos asignados exitosamente al grupo 'Cajero' y 'Gerente'.")

if __name__ == "__main__":
    setup_roles()
