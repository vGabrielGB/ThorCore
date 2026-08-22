from django import forms
from .models import Producto, TasaCambio, Categoria, MetodoPago

class MetodoPagoForm(forms.ModelForm):
    class Meta:
        model = MetodoPago
        fields = ['nombre', 'moneda', 'activo']
        widgets = {
            'nombre': forms.TextInput(attrs={'class': 'form-control'}),
            'moneda': forms.Select(attrs={'class': 'form-select'}),
            'activo': forms.CheckboxInput(attrs={'class': 'form-check-input'})
        }



class ProductoForm(forms.ModelForm):
    class Meta:
        model = Producto
        exclude = ['se_vende_al_mayor', 'precio_venta_mayor_usd_efectivo', 'precio_venta_mayor_usd_bcv']
        widgets = {
            'nombre': forms.TextInput(attrs={'class': 'form-control'}),
            'categoria': forms.Select(attrs={'class': 'form-control'}),
            'moneda_compra': forms.Select(attrs={'class': 'form-control'}),
            'moneda_venta': forms.Select(attrs={'class': 'form-control'}),
            'costo_base': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'tipo_medida': forms.Select(attrs={'class': 'form-control'}),
            'medida_cantidad_total': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'medida_cantidad_porcion': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'usar_ganancia_categoria': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'tipo_ganancia_personalizada': forms.Select(attrs={'class': 'form-control'}),
            'valor_ganancia_personalizada': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'cantidad_en_almacen': forms.NumberInput(attrs={'class': 'form-control'}),
            'cantidad_en_tienda': forms.NumberInput(attrs={'class': 'form-control'}),
        }



class TasaCambioForm(forms.ModelForm):
    class Meta:
        model = TasaCambio
        fields = ['tasa_real', 'tasa_margen']
        widgets = {
            'tasa_real': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'tasa_margen': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
        }

class CategoriaForm(forms.ModelForm):
    class Meta:
        model = Categoria
        fields = ['nombre', 'tipo_ganancia_default', 'valor_ganancia_default', 'se_vende_al_mayor_default', 'tipo_ganancia_mayor_default', 'valor_ganancia_mayor_default']
        widgets = {
            'nombre': forms.TextInput(attrs={'class': 'form-control'}),
            'se_vende_al_mayor_default': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'tipo_ganancia_default': forms.Select(attrs={'class': 'form-select'}),
            'valor_ganancia_default': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'tipo_ganancia_mayor_default': forms.Select(attrs={'class': 'form-select'}),
            'valor_ganancia_mayor_default': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['valor_ganancia_mayor_default'].required = False
        self.fields['tipo_ganancia_mayor_default'].required = False

    def clean(self):
        cleaned_data = super().clean()
        se_vende_mayor = cleaned_data.get('se_vende_al_mayor_default')
        if not se_vende_mayor:
            cleaned_data['valor_ganancia_mayor_default'] = 0
            if not cleaned_data.get('tipo_ganancia_mayor_default'):
                cleaned_data['tipo_ganancia_mayor_default'] = 'PORCENTAJE'
        else:
            if not cleaned_data.get('valor_ganancia_mayor_default'):
                self.add_error('valor_ganancia_mayor_default', 'Este campo es requerido si se vende al mayor por defecto.')
        return cleaned_data
