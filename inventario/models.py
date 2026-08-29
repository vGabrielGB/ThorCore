from django.db import models
from django.contrib.auth.models import User
import math
from decimal import Decimal
from django.core.cache import cache
from .utils import get_cached_rates, get_cached_config

class ConfiguracionNegocio(models.Model):
    TIPO_AUMENTO = [
        ('PORCENTAJE', 'Porcentaje'),
        ('FIJO', 'Monto Fijo USD/Bs'),
        ('MANUAL', 'Manual')
    ]
    
    factor_redondeo = models.IntegerField(default=20)
    # This old field might be deprecated now, but let's keep it to avoid deleting data if used elsewhere
    porcentaje_emergencia_bcv = models.DecimalField(max_digits=5, decimal_places=2, default=5.00)
    
    tipo_aumento_bcv = models.CharField(max_length=20, choices=TIPO_AUMENTO, default='PORCENTAJE')
    valor_aumento_bcv = models.DecimalField(max_digits=10, decimal_places=2, default=5.00)
    aumento_bcv_activo = models.BooleanField(default=True)
    
    aumento_usdt_activo = models.BooleanField(default=False)
    tipo_aumento_usdt = models.CharField(max_length=20, choices=TIPO_AUMENTO, default='PORCENTAJE')
    valor_aumento_usdt = models.DecimalField(max_digits=10, decimal_places=2, default=5.00)
    
    redondear_usd = models.BooleanField(default=False)
    valor_redondeo_usd = models.DecimalField(max_digits=10, decimal_places=2, default=0.50)
    redondear_ves = models.BooleanField(default=True)
    valor_redondeo_ves = models.DecimalField(max_digits=10, decimal_places=2, default=10.00)

    class Meta:
        verbose_name_plural = "Configuraciones del Negocio"

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        cache.delete('configuracion_negocio')

    def delete(self, *args, **kwargs):
        super().delete(*args, **kwargs)
        cache.delete('configuracion_negocio')

class TasaCambio(models.Model):
    moneda = models.CharField(max_length=20, primary_key=True) # 'BCV', 'USDT_VES', 'COP_USDT'
    tasa_real = models.DecimalField(max_digits=10, decimal_places=2)
    tasa_margen = models.DecimalField(max_digits=10, decimal_places=2)
    ultima_actualizacion = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.moneda} - Margen: {self.tasa_margen}"

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        cache.delete('tasas_cambio_dict')

    def delete(self, *args, **kwargs):
        super().delete(*args, **kwargs)
        cache.delete('tasas_cambio_dict')

class Categoria(models.Model):
    TIPO_GANANCIA = [
        ('PORCENTAJE', 'Porcentaje'),
        ('FIJO', 'Monto Fijo USD')
    ]
    nombre = models.CharField(max_length=15)
    
    tipo_ganancia_default = models.CharField(max_length=15, choices=TIPO_GANANCIA, default='PORCENTAJE')
    valor_ganancia_default = models.DecimalField(max_digits=10, decimal_places=2, default=30.00)
    
    se_vende_al_mayor_default = models.BooleanField(default=False)
    tipo_ganancia_mayor_default = models.CharField(max_length=15, choices=TIPO_GANANCIA, default='PORCENTAJE')
    valor_ganancia_mayor_default = models.DecimalField(max_digits=10, decimal_places=2, default=15.00)

    def __str__(self)-> str:
        return str(self.nombre)

class Producto(models.Model):
    MONEDA_COMPRA_CHOICES = [('COP', 'Pesos Colombianos'), ('USD', 'Dólares')]
    MONEDA_VENTA_CHOICES = [('VES', 'Bolívares'), ('USD', 'Dólares')]
    TIPO_GANANCIA = [('PORCENTAJE', 'Porcentaje'), ('FIJO', 'Monto Fijo USD')]

    nombre = models.CharField(max_length=20)
    categoria = models.ForeignKey(Categoria, on_delete=models.CASCADE)
    
    moneda_compra = models.CharField(max_length=20)
    moneda_venta = models.CharField(max_length=3, choices=MONEDA_VENTA_CHOICES, default='VES')
    
    costo_base = models.DecimalField(max_digits=12, decimal_places=2)
    
    # Nuevos campos de medidas
    TIPO_MEDIDA_CHOICES = [('KG', 'Kilogramos'), ('GR', 'Gramos'), ('UNIDAD', 'Unidades')]
    tipo_medida = models.CharField(max_length=10, choices=TIPO_MEDIDA_CHOICES, default='UNIDAD')
    medida_cantidad_total = models.DecimalField(max_digits=10, decimal_places=2, default=1.00)
    medida_cantidad_porcion = models.DecimalField(max_digits=10, decimal_places=2, default=1.00)
    
    se_vende_al_mayor = models.BooleanField(default=False)
    precio_venta_mayor_usd_efectivo = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    precio_venta_mayor_usd_bcv = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    
    usar_ganancia_categoria = models.BooleanField(default=True)
    tipo_ganancia_personalizada = models.CharField(max_length=15, choices=TIPO_GANANCIA, null=True, blank=True)
    valor_ganancia_personalizada = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    
    cantidad_en_almacen = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    cantidad_en_tienda = models.DecimalField(max_digits=12, decimal_places=2, default=0)

    def __str__(self)-> str:
        return str(self.nombre)

    def _obtener_numero_porciones(self):
        try:
            total = Decimal(str(self.medida_cantidad_total))
            porcion = Decimal(str(self.medida_cantidad_porcion))
            if porcion <= 0 or total <= 0: return Decimal('1')
            return total / porcion
        except:
            return Decimal('1')

    def _calcular_precio_total_sin_redondear(self, es_mayor=False):
        # 1. Llevar costo a USD
        costo_usd = Decimal(str(self.costo_base))
        rates = get_cached_rates()
        if self.moneda_compra != 'USD':
            tasa_obj = rates.get(self.moneda_compra)
            if tasa_obj and tasa_obj.tasa_real > 0:
                if self.moneda_compra.endswith('_USDT'):
                    costo_usd = costo_usd / tasa_obj.tasa_real
                elif self.moneda_compra.endswith('_BCV'):
                    costo_bcv = costo_usd / tasa_obj.tasa_real
                    tasa_bcv_usd = rates.get('BCV').tasa_real if 'BCV' in rates else Decimal('1')
                    costo_usd = costo_bcv / tasa_bcv_usd if tasa_bcv_usd > 0 else Decimal('0')
            else:
                return None

        # 2. Determinar la ganancia a aplicar (solo detal)
        if self.usar_ganancia_categoria:
            tipo_ganancia = self.categoria.tipo_ganancia_default
            valor_ganancia = Decimal(str(self.categoria.valor_ganancia_default))
        else:
            tipo_ganancia = self.tipo_ganancia_personalizada
            valor_ganancia = Decimal(str(self.valor_ganancia_personalizada or 0))

        # 3. Calcular precio en USD
        if tipo_ganancia == 'PORCENTAJE':
            return costo_usd * (Decimal('1') + (valor_ganancia / Decimal('100')))
        else: # FIJO
            return costo_usd + valor_ganancia

    @property
    def precio_venta_detal_porcion(self):
        """Calcula el PVP unitario (porción) redondeado"""
        try:
            precio_total_usd = self._calcular_precio_total_sin_redondear()
            if precio_total_usd is None: return None
            
            num_porciones = self._obtener_numero_porciones()
            precio_porcion_usd = precio_total_usd / num_porciones
            
            config = get_cached_config()
            rates = get_cached_rates()
            
            if self.moneda_venta == 'USD':
                if config and config.redondear_usd and config.valor_redondeo_usd > 0:
                    factor = float(config.valor_redondeo_usd)
                    precio_redondeado = math.ceil(float(precio_porcion_usd) / factor) * factor
                    return round(Decimal(precio_redondeado), 2)
                return round(precio_porcion_usd, 2)
                
            elif self.moneda_venta == 'VES':
                tasa = Decimal('0')
                if self.moneda_compra != 'USD' and 'USDT' in self.moneda_compra:
                    tasa = rates.get('USDT_VES').tasa_margen if 'USDT_VES' in rates else Decimal('0')
                else:
                    tasa = rates.get('BCV').tasa_margen if 'BCV' in rates else Decimal('0')
                
                precio_porcion_ves = precio_porcion_usd * tasa
                
                if config and config.redondear_ves and config.valor_redondeo_ves > 0:
                    factor = float(config.valor_redondeo_ves)
                    precio_redondeado = math.ceil(float(precio_porcion_ves) / factor) * factor
                    return round(Decimal(precio_redondeado), 2)
                
                return round(precio_porcion_ves, 2)
        except Exception:
            return None

    @property
    def precio_venta_publico(self):
        """PVP TOTAL del empaque en la moneda de venta, derivado de la porción redondeada"""
        pvp_porcion = self.precio_venta_detal_porcion
        if pvp_porcion is None: return None
        return round(pvp_porcion * self._obtener_numero_porciones(), 2)
        
    @property
    def pvp_detal_usd(self):
        """PVP TOTAL del empaque en USD siempre, para comparar con precios mayoristas en USD"""
        try:
            precio_total_usd = self._calcular_precio_total_sin_redondear()
            if precio_total_usd is None: return None
            
            num_porciones = self._obtener_numero_porciones()
            precio_porcion_usd = precio_total_usd / num_porciones
            
            config = get_cached_config()
            if config and config.redondear_usd and config.valor_redondeo_usd > 0:
                factor = float(config.valor_redondeo_usd)
                precio_redondeado = math.ceil(float(precio_porcion_usd) / factor) * factor
                pvp_porcion = round(Decimal(precio_redondeado), 2)
            else:
                pvp_porcion = round(precio_porcion_usd, 2)
                
            return round(pvp_porcion * num_porciones, 2)
        except:
            return None

    @property
    def costo_base_usd(self):
        costo = Decimal(str(self.costo_base))
        if self.moneda_compra != 'USD':
            try:
                rates = get_cached_rates()
                tasa_obj = rates.get(self.moneda_compra)
                if tasa_obj and tasa_obj.tasa_margen > 0:
                    if self.moneda_compra.endswith('_USDT'):
                        return round(costo / tasa_obj.tasa_margen, 2)
                    elif self.moneda_compra.endswith('_BCV'):
                        costo_bcv = costo / tasa_obj.tasa_margen
                        tasa_bcv_usd = rates.get('BCV').tasa_margen if 'BCV' in rates else Decimal('1')
                        if tasa_bcv_usd > 0:
                            return round(costo_bcv / tasa_bcv_usd, 2)
            except: pass
        return costo

    @property
    def precio_venta_mayor_bcv(self):
        """Calculates wholesale price in BCV if USD base is set"""
        if not self.se_vende_al_mayor or self.precio_venta_mayor_usd_bcv is None:
            return None
        try:
            rates = get_cached_rates()
            tasa_bcv = rates.get('BCV').tasa_margen if 'BCV' in rates else Decimal('0')
            return round(Decimal(str(self.precio_venta_mayor_usd_bcv)) * tasa_bcv, 2)
        except:
            return None

class VentaMayor(models.Model):
    METODO_PAGO_CHOICES = [
        ('EFECTIVO', 'Efectivo'),
        ('DOLARES_BCV', 'Dólares a BCV'),
    ]
    cliente = models.CharField(max_length=150)
    usuario = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)
    fecha = models.DateTimeField(auto_now_add=True)
    total_usd = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    es_credito = models.BooleanField(default=False)
    pagado = models.BooleanField(default=False)

    def __str__(self):
        return f"Venta Mayor #{self.id} - {self.cliente}"

class DetalleVentaMayor(models.Model):
    venta = models.ForeignKey(VentaMayor, on_delete=models.CASCADE, related_name='detalles')
    producto = models.ForeignKey(Producto, on_delete=models.CASCADE)
    cantidad = models.IntegerField()
    metodo_pago = models.CharField(max_length=20, choices=VentaMayor.METODO_PAGO_CHOICES, default='EFECTIVO')
    precio_unitario_usd = models.DecimalField(max_digits=12, decimal_places=2)
    subtotal_usd = models.DecimalField(max_digits=12, decimal_places=2)

    def __str__(self):
        return f"{self.cantidad} x {self.producto.nombre}"

class MetodoPago(models.Model):
    MONEDA_CHOICES = [
        ('USD', 'Dólares ($)'),
        ('VES', 'Bolívares (Bs)'),
    ]
    nombre = models.CharField(max_length=50, unique=True)
    moneda = models.CharField(max_length=3, choices=MONEDA_CHOICES, default='USD')
    activo = models.BooleanField(default=True)

    def __str__(self):
        return self.nombre

class CierreDiario(models.Model):
    fecha = models.DateField()
    usuario = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)
    total_usd = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    tasa_bcv = models.DecimalField(max_digits=12, decimal_places=4, default=0)
    creado_en = models.DateTimeField(auto_now_add=True)

    @property
    def is_editable(self):
        from django.utils import timezone
        return (timezone.now().date() - self.fecha).days <= 3

    def __str__(self):
        return f"Cierre {self.fecha} - Total: ${self.total_usd}"

class DetalleCierreDiario(models.Model):
    cierre = models.ForeignKey(CierreDiario, on_delete=models.CASCADE, related_name='detalles')
    metodo_pago = models.ForeignKey(MetodoPago, on_delete=models.PROTECT)
    monto_original = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    monto_usd = models.DecimalField(max_digits=12, decimal_places=2, default=0)

    def __str__(self):
        return f"{self.metodo_pago.nombre}: ${self.monto_usd}"

class MovimientoInventario(models.Model):
    TIPO_CHOICES = [
        ('ENTRADA', 'Entrada'),
        ('SALIDA', 'Salida'),
        ('AJUSTE', 'Ajuste Manual'),
    ]
    UBICACION_CHOICES = [
        ('TIENDA', 'Tienda'),
        ('ALMACEN', 'Almacén'),
    ]

    producto = models.ForeignKey(Producto, on_delete=models.CASCADE, related_name='movimientos')
    fecha = models.DateTimeField(auto_now_add=True)
    usuario = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)
    tipo = models.CharField(max_length=10, choices=TIPO_CHOICES)
    ubicacion = models.CharField(max_length=10, choices=UBICACION_CHOICES)
    cantidad = models.DecimalField(max_digits=12, decimal_places=2)
    motivo = models.CharField(max_length=255)
    stock_resultante = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)

    def __str__(self):
        return f"{self.tipo} - {self.cantidad} {self.producto.nombre} ({self.fecha})"

class VentaDetal(models.Model):
    cliente = models.CharField(max_length=150, blank=True, null=True)
    usuario = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)
    fecha = models.DateTimeField(auto_now_add=True)
    total_usd = models.DecimalField(max_digits=12, decimal_places=2, default=0)

    def __str__(self):
        return f"Venta Detal #{self.id}"

class DetalleVentaDetal(models.Model):
    venta = models.ForeignKey(VentaDetal, on_delete=models.CASCADE, related_name='detalles')
    producto = models.ForeignKey(Producto, on_delete=models.CASCADE)
    cantidad = models.DecimalField(max_digits=10, decimal_places=2)
    precio_unitario_usd = models.DecimalField(max_digits=12, decimal_places=2)
    subtotal_usd = models.DecimalField(max_digits=12, decimal_places=2)

    def __str__(self):
        return f"{self.cantidad} x {self.producto.nombre}"

class AbonoCredito(models.Model):
    venta = models.ForeignKey(VentaMayor, on_delete=models.CASCADE, related_name='abonos')
    fecha = models.DateTimeField(auto_now_add=True)
    monto_usd = models.DecimalField(max_digits=12, decimal_places=2)
    nota = models.CharField(max_length=255, blank=True)
    usuario = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)

    def __str__(self):
        return f"Abono de ${self.monto_usd} a Venta #{self.venta.id}"