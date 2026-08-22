from django.shortcuts import render, redirect, get_object_or_404
from django.http import JsonResponse
from django.utils import timezone
from django.db.models import Sum, F
from .models import TasaCambio, RegistroIngresoSaco, Producto, ConfiguracionNegocio, Categoria, VentaMayor, DetalleVentaMayor
from .forms import ProductoForm, RegistroVentaForm, TasaCambioForm, CategoriaForm
from decimal import Decimal
from django.contrib import messages
from .utils import scrape_bcv_rate
from django.http import HttpResponse
from reportlab.lib.pagesizes import letter
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet
import math

def dashboard_view(request):
    today = timezone.now()
    
    tasas = TasaCambio.objects.all()
    
    ventas_hoy = RegistroIngresoSaco.objects.filter(
        fecha__date=today.date()
    ).aggregate(total_usd=Sum('ingreso_bruto_usd'))['total_usd'] or Decimal('0.00')
    
    ventas_mes = RegistroIngresoSaco.objects.filter(
        fecha__year=today.year,
        fecha__month=today.month
    ).aggregate(total_usd=Sum('ingreso_bruto_usd'))['total_usd'] or Decimal('0.00')
    
    ventas_recientes = RegistroIngresoSaco.objects.order_by('-fecha')[:5]
    
    productos_bajo_stock = Producto.objects.annotate(
        stock_total=F('cantidad_en_tienda') + F('cantidad_en_almacen')
    ).filter(stock_total__lte=5).order_by('stock_total')[:5]
    
    context = {
        'tasas': tasas,
        'ventas_hoy': ventas_hoy,
        'ventas_mes': ventas_mes,
        'ventas_recientes': ventas_recientes,
        'productos_bajo_stock': productos_bajo_stock,
    }
    return render(request, 'inventario/dashboard.html', context)

def producto_list_view(request):
    productos = Producto.objects.select_related('categoria').all().order_by('nombre')
    categorias = Categoria.objects.all().order_by('nombre')
    
    q = request.GET.get('q', '')
    categoria_id = request.GET.get('categoria', '')
    
    if q:
        productos = productos.filter(nombre__icontains=q)
    if categoria_id:
        productos = productos.filter(categoria_id=categoria_id)
        
    form = ProductoForm()
    context = {
        'productos': productos,
        'categorias': categorias,
        'q': q,
        'categoria_id': categoria_id,
        'form': form,
        'open_modal': False
    }
    return render(request, 'inventario/productos_list.html', context)

def producto_create_view(request):
    if request.method == 'POST':
        form = ProductoForm(request.POST)
        is_ajax = request.headers.get('x-requested-with') == 'XMLHttpRequest' or request.POST.get('is_ajax')
        
        if form.is_valid():
            producto = form.save()
            if is_ajax:
                return JsonResponse({'success': True, 'producto_id': producto.id})
            messages.success(request, 'Producto guardado correctamente.')
            return redirect('inventario:producto_list')
        else:
            if is_ajax:
                return JsonResponse({'success': False, 'errors': form.errors})
            
            productos = Producto.objects.select_related('categoria').all().order_by('nombre')
            categorias = Categoria.objects.all().order_by('nombre')
            context = {
                'productos': productos,
                'categorias': categorias,
                'q': '',
                'categoria_id': '',
                'form': form,
                'open_modal': True
            }
            return render(request, 'inventario/productos_list.html', context)
    return redirect('inventario:producto_list')

def producto_update_mayor_view(request, pk):
    if request.method == 'POST':
        producto = get_object_or_404(Producto, pk=pk)
        
        if 'se_vende_al_mayor' in request.POST:
            val = request.POST.get('se_vende_al_mayor').lower()
            producto.se_vende_al_mayor = (val == 'true' or val == 'on')
            
        # Si envían precios al mayor
        efectivo = request.POST.get('precio_venta_mayor_usd_efectivo')
        bcv = request.POST.get('precio_venta_mayor_usd_bcv')
        
        if efectivo is not None or bcv is not None:
            val_efectivo = Decimal(efectivo) if efectivo else None
            val_bcv = Decimal(bcv) if bcv else None
            
            # Validación: No ganar más al mayor que al detal
            pvp_total_detal_usd = producto.precio_venta_publico
            if pvp_total_detal_usd:
                if producto.moneda_venta == 'VES':
                    try:
                        tasa_bcv = TasaCambio.objects.get(moneda='BCV').tasa_margen
                        pvp_total_detal_usd = pvp_total_detal_usd / tasa_bcv
                    except:
                        pass
                
                # Check validation
                if val_efectivo and val_efectivo > pvp_total_detal_usd:
                    return JsonResponse({'success': False, 'error': 'El precio en efectivo no puede ser mayor al PVP Total del detal.'})
                if val_bcv and val_bcv > pvp_total_detal_usd:
                    return JsonResponse({'success': False, 'error': 'El precio base BCV no puede ser mayor al PVP Total del detal.'})
            
            if val_efectivo is not None:
                producto.precio_venta_mayor_usd_efectivo = val_efectivo
            if val_bcv is not None:
                producto.precio_venta_mayor_usd_bcv = val_bcv
                
        producto.save()
        return JsonResponse({'success': True})
    return JsonResponse({'success': False, 'error': 'Invalid request method'})

def producto_update_stock_view(request, pk):
    if request.method == 'POST':
        producto = get_object_or_404(Producto, pk=pk)
        try:
            producto.cantidad_en_tienda = int(request.POST.get('cantidad_en_tienda', 0))
            producto.cantidad_en_almacen = int(request.POST.get('cantidad_en_almacen', 0))
            producto.save()
            return JsonResponse({'success': True})
        except ValueError:
            return JsonResponse({'success': False, 'error': 'Cantidades inválidas'})
    return JsonResponse({'success': False, 'error': 'Invalid request method'})

def producto_edit_view(request, pk):
    producto = get_object_or_404(Producto, pk=pk)
    
    if request.headers.get('x-requested-with') == 'XMLHttpRequest':
        if request.method == 'GET':
            form = ProductoForm(instance=producto)
            return render(request, 'inventario/formulario_generico_partial.html', {'form': form, 'title': 'Editar Producto'})
        elif request.method == 'POST':
            form = ProductoForm(request.POST, instance=producto)
            if form.is_valid():
                form.save()
                return JsonResponse({'success': True})
            else:
                return JsonResponse({'success': False, 'error': form.errors.as_json()})
                
    if request.method == 'POST':
        form = ProductoForm(request.POST, instance=producto)
        if form.is_valid():
            form.save()
            messages.success(request, 'Producto actualizado correctamente.')
            return redirect('inventario:producto_list')
    else:
        form = ProductoForm(instance=producto)
    return render(request, 'inventario/formulario_generico.html', {'form': form, 'title': 'Editar Producto'})

def producto_delete_view(request, pk):
    producto = get_object_or_404(Producto, pk=pk)
    nombre = producto.nombre
    producto.delete()
    messages.success(request, f'Producto "{nombre}" eliminado con éxito.')
    return redirect('inventario:producto_list')

def ventas_list_view(request):
    ventas = RegistroIngresoSaco.objects.all().order_by('-fecha')
    return render(request, 'inventario/ventas_list.html', {'ventas': ventas})

def venta_create_view(request):
    if request.method == 'POST':
        form = RegistroVentaForm(request.POST)
        if form.is_valid():
            venta = form.save(commit=False)
            prod = venta.producto
            ingreso = Decimal('20.00') * venta.cantidad_sacos_vendidos if prod.moneda_compra == 'COP' else prod.costo_base * venta.cantidad_sacos_vendidos * Decimal('1.3')
            venta.ingreso_bruto_usd = round(ingreso, 2)
            
            if prod.cantidad_en_tienda >= venta.cantidad_sacos_vendidos:
                prod.cantidad_en_tienda -= venta.cantidad_sacos_vendidos
                prod.save()
                venta.save()
                messages.success(request, 'Venta registrada correctamente.')
                return redirect('inventario:ventas_list')
            else:
                messages.error(request, 'No hay suficiente stock en tienda para esta venta.')
    else:
        form = RegistroVentaForm()
    return render(request, 'inventario/formulario_generico.html', {'form': form, 'title': 'Registrar Apertura Detal'})

def productos_mayor_list_view(request):
    productos = Producto.objects.filter(se_vende_al_mayor=True).select_related('categoria').order_by('nombre')
    return render(request, 'inventario/productos_mayor_list.html', {'productos': productos})

def ventas_mayor_list_view(request):
    ventas = VentaMayor.objects.all().order_by('-fecha')
    return render(request, 'inventario/ventas_mayor_list.html', {'ventas': ventas})

import json
def venta_mayor_create_view(request):
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            cliente = data.get('cliente', '')
            items = data.get('items', [])
            
            if not cliente or not items:
                return JsonResponse({'success': False, 'error': 'Faltan datos'})
                
            total = Decimal('0.00')
            venta = VentaMayor.objects.create(cliente=cliente, usuario=request.user if request.user.is_authenticated else None)
            
            for item in items:
                producto = get_object_or_404(Producto, pk=item['id'])
                cantidad = int(item['cantidad'])
                
                origen = item.get('origen', 'ALMACEN')
                
                # Descontar según el origen
                if origen == 'ALMACEN':
                    if producto.cantidad_en_almacen >= cantidad:
                        producto.cantidad_en_almacen -= cantidad
                        producto.save()
                    else:
                        venta.delete()
                        return JsonResponse({'success': False, 'error': f'Stock insuficiente en almacén para {producto.nombre}'})
                else:
                    if producto.cantidad_en_tienda >= cantidad:
                        producto.cantidad_en_tienda -= cantidad
                        producto.save()
                    else:
                        venta.delete()
                        return JsonResponse({'success': False, 'error': f'Stock insuficiente en tienda para {producto.nombre}'})
                
                precio = producto.precio_venta_mayor or Decimal('0')
                subtotal = precio * cantidad
                total += subtotal
                
                DetalleVentaMayor.objects.create(
                    venta=venta,
                    producto=producto,
                    cantidad=cantidad,
                    precio_unitario_usd=precio,
                    subtotal_usd=subtotal
                )
                
            venta.total_usd = total
            venta.save()
            
            return JsonResponse({'success': True, 'venta_id': venta.id})
        except Exception as e:
            return JsonResponse({'success': False, 'error': str(e)})
            
    productos = Producto.objects.filter(se_vende_al_mayor=True, cantidad_en_almacen__gt=0).order_by('nombre')
    return render(request, 'inventario/venta_mayor_create.html', {'productos': productos})

def tasas_list_view(request):
    tasas = TasaCambio.objects.all()
    return render(request, 'inventario/tasas_list.html', {'tasas': tasas})

def tasa_edit_view(request, pk):
    tasa = get_object_or_404(TasaCambio, pk=pk)
    config = ConfiguracionNegocio.objects.first()
    
    if request.method == 'POST':
        form = TasaCambioForm(request.POST, instance=tasa)
        if form.is_valid():
            form.save()
            
            if tasa.moneda == 'BCV' and config:
                config.tipo_aumento_bcv = request.POST.get('tipo_aumento_bcv', config.tipo_aumento_bcv)
                config.valor_aumento_bcv = request.POST.get('valor_aumento_bcv', config.valor_aumento_bcv)
                config.save()
                
            messages.success(request, 'Tasa actualizada correctamente.')
            return redirect('inventario:tasas_list')
    else:
        form = TasaCambioForm(instance=tasa)
    
    return render(request, 'inventario/formulario_generico.html', {
        'form': form, 
        'title': f'Editar Tasa {tasa.moneda}',
        'tasa_obj': tasa,
        'config': config
    })

def scrape_bcv_view(request):
    rate, err = scrape_bcv_rate()
    if err:
        messages.error(request, err)
    elif rate:
        tasa_obj, _ = TasaCambio.objects.get_or_create(
            moneda='BCV', 
            defaults={'tasa_real': rate, 'tasa_margen': rate}
        )
        
        if rate <= tasa_obj.tasa_margen:
            tasa_obj.tasa_real = rate
            tasa_obj.save()
            messages.success(request, f'Tasa BCV sincronizada ({rate}). Tu margen actual ({tasa_obj.tasa_margen}) se mantiene porque el BCV no lo superó.')
        else:
            config = ConfiguracionNegocio.objects.first()
            if not config:
                config = ConfiguracionNegocio.objects.create()
                
            tasa_obj.tasa_real = rate
            
            if config.tipo_aumento_bcv == 'PORCENTAJE':
                nuevo_margen = rate * (Decimal('1') + (config.valor_aumento_bcv / Decimal('100')))
                tasa_obj.tasa_margen = round(nuevo_margen, 2)
                tasa_obj.save()
                messages.success(request, f'Tasa BCV subió a {rate}. Margen actualizado a {tasa_obj.tasa_margen} (+{config.valor_aumento_bcv}%).')
            elif config.tipo_aumento_bcv == 'FIJO':
                nuevo_margen = rate + config.valor_aumento_bcv
                tasa_obj.tasa_margen = round(nuevo_margen, 2)
                tasa_obj.save()
                messages.success(request, f'Tasa BCV subió a {rate}. Margen actualizado a {tasa_obj.tasa_margen} (+{config.valor_aumento_bcv} Bs).')
            elif config.tipo_aumento_bcv == 'MANUAL':
                tasa_obj.save() 
                messages.warning(request, f'¡Alerta! BCV subió a {rate} y superó tu margen actual ({tasa_obj.tasa_margen}). Como estás en modo manual, el margen no se actualizó automáticamente.')
                
    return redirect('inventario:tasas_list')

def categoria_list_view(request):
    categorias = Categoria.objects.all().order_by('nombre')
    return render(request, 'inventario/categorias_list.html', {'categorias': categorias})

def centro_control_view(request):
    categorias = Categoria.objects.all().order_by('nombre')
    tasas = TasaCambio.objects.all()
    return render(request, 'inventario/centro_control.html', {'categorias': categorias, 'tasas': tasas})

def categoria_create_view(request):
    if request.method == 'POST':
        form = CategoriaForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, 'Categoría creada con éxito.')
            return redirect('inventario:categoria_list')
    else:
        form = CategoriaForm()
    return render(request, 'inventario/formulario_generico.html', {
        'form': form,
        'title': 'Nueva Categoría',
        'button_text': 'Guardar',
        'back_url': 'inventario:categoria_list'
    })

def categoria_edit_view(request, pk):
    categoria = get_object_or_404(Categoria, pk=pk)
    if request.method == 'POST':
        form = CategoriaForm(request.POST, instance=categoria)
        if form.is_valid():
            form.save()
            messages.success(request, 'Categoría actualizada.')
            return redirect('inventario:categoria_list')
    else:
        form = CategoriaForm(instance=categoria)
    return render(request, 'inventario/formulario_generico.html', {
        'form': form,
        'title': f'Editar Categoría: {categoria.nombre}',
        'button_text': 'Actualizar',
        'back_url': 'inventario:categoria_list'
    })

def producto_export_pdf_view(request):
    productos = Producto.objects.select_related('categoria').all().order_by('nombre')
    q = request.GET.get('q', '')
    categoria_id = request.GET.get('categoria', '')
    
    if q:
        productos = productos.filter(nombre__icontains=q)
    if categoria_id:
        productos = productos.filter(categoria_id=categoria_id)
        
    response = HttpResponse(content_type='application/pdf')
    response['Content-Disposition'] = 'attachment; filename="Listado_Productos.pdf"'
    
    doc = SimpleDocTemplate(response, pagesize=letter)
    elements = []
    
    styles = getSampleStyleSheet()
    title_text = "Listado de Productos Agrothor"
    if categoria_id:
        try:
            cat_nombre = Categoria.objects.get(id=categoria_id).nombre
            title_text += f" - {cat_nombre}"
        except:
            pass
    
    elements.append(Paragraph(title_text, styles['Title']))
    elements.append(Spacer(1, 12))
    
    # Agrupar por categoría
    categorias_dict = {}
    for p in productos:
        cat_name = p.categoria.nombre
        if cat_name not in categorias_dict:
            categorias_dict[cat_name] = []
        categorias_dict[cat_name].append(p)
        
    for cat_name, prods in categorias_dict.items():
        elements.append(Paragraph(cat_name, styles['Heading2']))
        elements.append(Spacer(1, 6))
        
        data = [["ID", "Nombre", "PVP Porción"]]
        
        for p in prods:
            pvp_kg = "N/A"
            if p.precio_venta_por_porcion:
                pvp_kg = f"{p.precio_venta_por_porcion:.2f} {p.moneda_venta}"
                
            data.append([
                f"#{p.id}",
                p.nombre,
                pvp_kg
            ])
            
        table = Table(data, colWidths=[60, 300, 140])
        table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('ALIGN', (1, 0), (1, -1), 'LEFT'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 10),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
            ('BACKGROUND', (0, 1), (-1, -1), colors.beige),
            ('TEXTCOLOR', (0, 1), (-1, -1), colors.black),
            ('FONTNAME', (0, 1), (-1, -1), 'Helvetica'),
            ('FONTSIZE', (0, 1), (-1, -1), 9),
            ('GRID', (0, 0), (-1, -1), 1, colors.black)
        ]))
        
        elements.append(table)
        elements.append(Spacer(1, 12))
        
    doc.build(elements)
    
    return response

def producto_export_pdf_mayor_view(request):
    productos = Producto.objects.filter(se_vende_al_mayor=True).select_related('categoria').order_by('nombre')
    
    response = HttpResponse(content_type='application/pdf')
    response['Content-Disposition'] = 'attachment; filename="Listado_Mayoristas.pdf"'
    
    doc = SimpleDocTemplate(response, pagesize=letter)
    elements = []
    styles = getSampleStyleSheet()
    
    elements.append(Paragraph("Listado de Productos al Mayor - Agrothor", styles['Title']))
    elements.append(Spacer(1, 12))
    
    categorias_dict = {}
    for p in productos:
        cat_name = p.categoria.nombre
        if cat_name not in categorias_dict:
            categorias_dict[cat_name] = []
        categorias_dict[cat_name].append(p)
        
    for cat_name, prods in categorias_dict.items():
        elements.append(Paragraph(cat_name, styles['Heading2']))
        elements.append(Spacer(1, 6))
        
        data = [["ID", "Nombre", "PVP Mayor Efectivo ($)", "PVP Mayor BCV (Bs)"]]
        
        for p in prods:
            pvp_usd_eff = f"{p.precio_venta_mayor_usd_efectivo} $" if p.precio_venta_mayor_usd_efectivo else "N/A"
            pvp_bs = f"{p.precio_venta_mayor_bcv} Bs" if p.precio_venta_mayor_bcv else "N/A"
                
            data.append([
                f"#{p.id}",
                p.nombre,
                pvp_usd_eff,
                pvp_bs
            ])
            
        table = Table(data, colWidths=[60, 240, 100, 100])
        table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('ALIGN', (1, 0), (1, -1), 'LEFT'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 10),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
            ('BACKGROUND', (0, 1), (-1, -1), colors.beige),
            ('TEXTCOLOR', (0, 1), (-1, -1), colors.black),
            ('FONTNAME', (0, 1), (-1, -1), 'Helvetica'),
            ('FONTSIZE', (0, 1), (-1, -1), 9),
            ('GRID', (0, 0), (-1, -1), 1, colors.black)
        ]))
        
        elements.append(table)
        elements.append(Spacer(1, 12))
        
    doc.build(elements)
    
    return response