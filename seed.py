import os
import sys
import django
from decimal import Decimal
from django.utils import timezone
from datetime import timedelta
import random

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from django.contrib.auth.models import User
from inventario.models import ConfiguracionNegocio, TasaCambio, Categoria, Producto, RegistroIngresoSaco

def seed():
    print("Iniciando carga de datos...")

    # 1. Crear Superusuario
    if not User.objects.filter(username='admin').exists():
        User.objects.create_superuser('admin', 'admin@example.com', 'admin123')
        print("- Superusuario 'admin' creado.")
    user = User.objects.get(username='admin')

    # 2. Configuración
    if not ConfiguracionNegocio.objects.exists():
        ConfiguracionNegocio.objects.create(factor_redondeo=20, porcentaje_emergencia_bcv=5.00)
        print("- Configuración inicial creada.")

    # 3. Tasas de Cambio
    tasas = [
        {'moneda': 'BCV', 'tasa_real': 36.50, 'tasa_margen': 38.32},
        {'moneda': 'USDT_VES', 'tasa_real': 40.00, 'tasa_margen': 40.50},
        {'moneda': 'COP_USDT', 'tasa_real': 4000.00, 'tasa_margen': 4050.00},
    ]
    for t in tasas:
        TasaCambio.objects.update_or_create(moneda=t['moneda'], defaults=t)
    print("- Tasas de cambio configuradas.")

    # 4. Categorías
    categorias = [
        {'nombre': 'Alimento Perro Premium', 'es_alimento': True, 'tipo_ganancia_default': 'PORCENTAJE', 'valor_ganancia_default': 30.00},
        {'nombre': 'Alimento Gato Estandar', 'es_alimento': True, 'tipo_ganancia_default': 'PORCENTAJE', 'valor_ganancia_default': 25.00},
        {'nombre': 'Accesorios', 'es_alimento': False, 'tipo_ganancia_default': 'FIJO', 'valor_ganancia_default': 5.00},
    ]
    for c in categorias:
        Categoria.objects.update_or_create(nombre=c['nombre'], defaults=c)
    print("- Categorías creadas.")

    cat_perro = Categoria.objects.get(nombre='Alimento Perro Premium')
    cat_gato = Categoria.objects.get(nombre='Alimento Gato Estandar')

    # 5. Productos
    productos = [
        {'nombre': 'Dog Chow Adultos 20kg', 'categoria': cat_perro, 'moneda_compra': 'COP', 'costo_base': 80000.00, 'cantidad_en_almacen': 10, 'cantidad_en_tienda': 5},
        {'nombre': 'Pedigree Cachorros 15kg', 'categoria': cat_perro, 'moneda_compra': 'USD', 'costo_base': 25.00, 'cantidad_en_almacen': 2, 'cantidad_en_tienda': 2},
        {'nombre': 'Cat Chow Pescado 15kg', 'categoria': cat_gato, 'moneda_compra': 'COP', 'costo_base': 75000.00, 'cantidad_en_almacen': 1, 'cantidad_en_tienda': 1},
        {'nombre': 'Gatarina Económica 10kg', 'categoria': cat_gato, 'moneda_compra': 'USD', 'costo_base': 15.00, 'cantidad_en_almacen': 20, 'cantidad_en_tienda': 10},
    ]
    for p in productos:
        Producto.objects.update_or_create(nombre=p['nombre'], defaults=p)
    print("- Productos creados.")

    # 6. Ventas recientes
    if RegistroIngresoSaco.objects.count() == 0:
        prods = list(Producto.objects.all())
        now = timezone.now()
        for i in range(15):
            prod = random.choice(prods)
            cant = random.randint(1, 3)
            # simulate a price roughly
            ingreso = Decimal('20.00') * cant if prod.moneda_compra == 'COP' else prod.costo_base * cant * Decimal('1.3')
            
            venta = RegistroIngresoSaco.objects.create(
                producto=prod,
                usuario=user,
                cantidad_sacos_vendidos=cant,
                ingreso_bruto_usd=round(ingreso, 2)
            )
            # Randomize dates within the last 30 days
            venta.fecha = now - timedelta(days=random.randint(0, 20), hours=random.randint(1, 23))
            venta.save()
        print("- 15 Registros de ventas creados.")

    print("Carga finalizada con éxito!")

if __name__ == '__main__':
    seed()
