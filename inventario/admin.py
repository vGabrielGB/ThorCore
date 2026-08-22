from django.contrib import admin
from .models import ConfiguracionNegocio, TasaCambio, Categoria, Producto

@admin.register(ConfiguracionNegocio)
class ConfiguracionNegocioAdmin(admin.ModelAdmin):
    list_display = ['id', 'factor_redondeo', 'porcentaje_emergencia_bcv']

@admin.register(TasaCambio)
class TasaCambioAdmin(admin.ModelAdmin):
    list_display = ['moneda', 'tasa_real', 'tasa_margen', 'ultima_actualizacion']
    list_editable = ['tasa_real', 'tasa_margen']
    search_fields = ['moneda']

@admin.register(Categoria)
class CategoriaAdmin(admin.ModelAdmin):
    list_display = ['nombre', 'tipo_ganancia_default', 'valor_ganancia_default']
    list_filter = ['tipo_ganancia_default']
    search_fields = ['nombre']

@admin.register(Producto)
class ProductoAdmin(admin.ModelAdmin):
    list_display = ['nombre', 'categoria', 'moneda_compra', 'moneda_venta', 'costo_base', 'get_precio_venta_publico']
    list_filter = ['categoria', 'moneda_compra', 'moneda_venta', 'usar_ganancia_categoria']
    search_fields = ['nombre']
    readonly_fields = ['precio_venta_publico']

    def get_precio_venta_publico(self, obj):
        precio = obj.precio_venta_publico
        if precio is None:
            return "Faltan Tasas"
        return f"{precio:,.2f} {obj.moneda_venta}"
    get_precio_venta_publico.short_description = "PVP Final"
