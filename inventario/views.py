from django.shortcuts import render, redirect, get_object_or_404
from .decorators import cajero_gerente_required, gerente_required, superuser_required
from django.http import JsonResponse
from django.utils import timezone
from django.db import transaction
from django.db.models import Sum, F
from .models import TasaCambio, Producto, ConfiguracionNegocio, Categoria, VentaMayor, DetalleVentaMayor, MovimientoInventario, VentaDetal, DetalleVentaDetal, MetodoPago, CierreDiario, DetalleCierreDiario, AbonoCredito
from .forms import ProductoForm, TasaCambioForm, CategoriaForm, MetodoPagoForm
from decimal import Decimal
from django.contrib import messages
from .utils import scrape_bcv_rate, scrape_binance_usdt, get_cached_rates
from django.http import HttpResponse
from reportlab.lib.pagesizes import letter
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet
import math

@cajero_gerente_required
def dashboard_view(request):
    if request.user.groups.filter(name='Cajero').exists():
        return redirect('inventario:ventas_list')
        
    today = timezone.now()
    from datetime import timedelta
    ayer = (today - timedelta(days=1)).date()
    
    tasas = TasaCambio.objects.all()
    
    ventas_ayer = CierreDiario.objects.filter(
        fecha=ayer
    ).aggregate(total=Sum('total_usd'))['total'] or Decimal('0.00')
    
    ventas_mes = CierreDiario.objects.filter(
        fecha__year=today.year,
        fecha__month=today.month
    ).aggregate(total=Sum('total_usd'))['total'] or Decimal('0.00')
    
    # Obtener las últimas ventas (mix de mayor y detal)
    ultimas_mayor = list(VentaMayor.objects.order_by('-fecha')[:5])
    ultimas_detal = list(VentaDetal.objects.order_by('-fecha')[:5])
    
    ventas_recientes_raw = ultimas_mayor + ultimas_detal
    ventas_recientes_raw.sort(key=lambda x: x.fecha, reverse=True)
    
    ventas_recientes = []
    for v in ventas_recientes_raw[:5]:
        tipo = "Al Mayor" if isinstance(v, VentaMayor) else "Al Detal"
        # Tratar de obtener un resumen de productos
        detalles = v.detalles.all()
        if detalles.exists():
            desc = ", ".join([f"{d.cantidad}x {d.producto.nombre}" for d in detalles])
        else:
            desc = "Sin detalles"
            
        ventas_recientes.append({
            'descripcion': desc,
            'tipo': tipo,
            'total_usd': v.total_usd,
            'fecha': v.fecha
        })
    
    productos_bajo_stock = Producto.objects.annotate(
        stock_total=F('cantidad_en_tienda') + F('cantidad_en_almacen')
    ).filter(stock_total__lte=5).order_by('stock_total')[:5]
    
    context = {
        'tasas': tasas,
        'ventas_ayer': ventas_ayer,
        'ventas_mes': ventas_mes,
        'ventas_recientes': ventas_recientes,
        'productos_bajo_stock': productos_bajo_stock,
    }
    return render(request, 'inventario/dashboard.html', context)

@gerente_required
def producto_list_view(request):
    from django.core.paginator import Paginator
    productos = Producto.objects.select_related('categoria').all().order_by('nombre')
    categorias = Categoria.objects.all().order_by('nombre')
    
    q = request.GET.get('q', '')
    categoria_id = request.GET.get('categoria', '')
    
    if q:
        productos = productos.filter(nombre__icontains=q)
    if categoria_id:
        productos = productos.filter(categoria_id=categoria_id)
        
    paginator = Paginator(productos, 25)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
        
    tasas = TasaCambio.objects.exclude(moneda__in=['BCV', 'USDT_VES'])
    
    form = ProductoForm()
    context = {
        'page_obj': page_obj,
        'productos': page_obj.object_list,
        'categorias': categorias,
        'tasas': tasas,
        'q': q,
        'categoria_id': categoria_id,
        'form': form,
        'open_modal': False
    }
    return render(request, 'inventario/productos_list.html', context)

@gerente_required
def producto_create_view(request):
    if request.method == 'POST':
        form = ProductoForm(request.POST)
        is_ajax = request.headers.get('x-requested-with') == 'XMLHttpRequest' or request.POST.get('is_ajax')
        
        if form.is_valid():
            producto = form.save()
            usuario_actual = request.user if request.user.is_authenticated else None
            if producto.cantidad_en_tienda > 0:
                MovimientoInventario.objects.create(producto=producto, usuario=usuario_actual, tipo='ENTRADA', ubicacion='TIENDA', cantidad=producto.cantidad_en_tienda, motivo='Inventario inicial', stock_resultante=producto.cantidad_en_tienda)
            if producto.cantidad_en_almacen > 0:
                MovimientoInventario.objects.create(producto=producto, usuario=usuario_actual, tipo='ENTRADA', ubicacion='ALMACEN', cantidad=producto.cantidad_en_almacen, motivo='Inventario inicial', stock_resultante=producto.cantidad_en_almacen)
            if is_ajax:
                return JsonResponse({'success': True, 'producto_id': producto.id})
            messages.success(request, 'Producto guardado correctamente.')
            return redirect('inventario:producto_list')
        else:
            if is_ajax:
                return JsonResponse({'success': False, 'errors': form.errors})
            
            productos = Producto.objects.select_related('categoria').all().order_by('nombre')
            categorias = Categoria.objects.all().order_by('nombre')
            tasas = TasaCambio.objects.exclude(moneda__in=['BCV', 'USDT_VES'])
            context = {
                'productos': productos,
                'categorias': categorias,
                'tasas': tasas,
                'q': '',
                'categoria_id': '',
                'form': form,
                'open_modal': True
            }
            return render(request, 'inventario/productos_list.html', context)
    return redirect('inventario:producto_list')

@gerente_required
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
            pvp_total_detal_usd = producto.pvp_detal_usd
            if pvp_total_detal_usd:
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

@gerente_required
def producto_update_stock_view(request, pk):
    if request.method == 'POST':
        producto = get_object_or_404(Producto, pk=pk)
        try:
            nueva_tienda = int(request.POST.get('cantidad_en_tienda', 0))
            nueva_almacen = int(request.POST.get('cantidad_en_almacen', 0))
            diff_tienda = nueva_tienda - producto.cantidad_en_tienda
            diff_almacen = nueva_almacen - producto.cantidad_en_almacen
            usuario_actual = request.user if request.user.is_authenticated else None

            if diff_tienda != 0:
                MovimientoInventario.objects.create(producto=producto, usuario=usuario_actual, tipo='AJUSTE', ubicacion='TIENDA', cantidad=abs(diff_tienda), motivo='Ajuste de inventario manual', stock_resultante=nueva_tienda)
            if diff_almacen != 0:
                MovimientoInventario.objects.create(producto=producto, usuario=usuario_actual, tipo='AJUSTE', ubicacion='ALMACEN', cantidad=abs(diff_almacen), motivo='Ajuste de inventario manual', stock_resultante=nueva_almacen)

            producto.cantidad_en_tienda = nueva_tienda
            producto.cantidad_en_almacen = nueva_almacen
            producto.save()
            return JsonResponse({'success': True})
        except ValueError:
            return JsonResponse({'success': False, 'error': 'Cantidades inválidas'})
    return JsonResponse({'success': False, 'error': 'Invalid request method'})

@gerente_required
def producto_edit_view(request, pk):
    producto = get_object_or_404(Producto, pk=pk)
    
    if request.headers.get('x-requested-with') == 'XMLHttpRequest':
        if request.method == 'GET':
            form = ProductoForm(instance=producto)
            return render(request, 'inventario/formulario_generico_partial.html', {'form': form, 'title': 'Editar Producto'})
        elif request.method == 'POST':
            form = ProductoForm(request.POST, instance=producto)
            if form.is_valid():
                producto = form.save()
                
                warning_msg = None
                if producto.se_vende_al_mayor:
                    pvp_detal = producto.precio_venta_publico
                    if pvp_detal:
                        mayor_efectivo = producto.precio_venta_mayor_usd_efectivo or 0
                        mayor_bcv = producto.precio_venta_mayor_usd_bcv or 0
                        if mayor_efectivo > pvp_detal or mayor_bcv > pvp_detal:
                            warning_msg = 'Atención: El PVP al Detal ha quedado por debajo del precio al mayor. Deberías ajustar el precio al mayor.'
                            
                return JsonResponse({'success': True, 'warning': warning_msg})
            else:
                return JsonResponse({'success': False, 'error': form.errors.as_json()})
                
    if request.method == 'POST':
        form = ProductoForm(request.POST, instance=producto)
        if form.is_valid():
            producto = form.save()
            
            warning_msg = None
            if producto.se_vende_al_mayor:
                pvp_detal = producto.precio_venta_publico
                if pvp_detal:
                    mayor_efectivo = producto.precio_venta_mayor_usd_efectivo or 0
                    mayor_bcv = producto.precio_venta_mayor_usd_bcv or 0
                    if mayor_efectivo > pvp_detal or mayor_bcv > pvp_detal:
                        warning_msg = 'Atención: El PVP al Detal ha quedado por debajo del precio al mayor. Deberías ajustar el precio al mayor.'
            
            if warning_msg:
                messages.warning(request, warning_msg)
            else:
                messages.success(request, 'Producto actualizado correctamente.')
            return redirect('inventario:producto_list')
    else:
        form = ProductoForm(instance=producto)
    return render(request, 'inventario/formulario_generico.html', {'form': form, 'title': 'Editar Producto'})

@gerente_required
def producto_delete_view(request, pk):
    producto = get_object_or_404(Producto, pk=pk)
    nombre = producto.nombre
    producto.delete()
    messages.success(request, f'Producto "{nombre}" eliminado con éxito.')
    return redirect('inventario:producto_list')

@cajero_gerente_required
def ventas_list_view(request):
    from django.core.paginator import Paginator
    ventas = VentaDetal.objects.all().order_by('-fecha')
    paginator = Paginator(ventas, 50)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    productos = Producto.objects.filter(cantidad_en_tienda__gt=0).order_by('nombre')
    
    return render(request, 'inventario/ventas_list.html', {
        'page_obj': page_obj,
        'productos': productos
    })

@gerente_required
def productos_mayor_list_view(request):
    from django.core.paginator import Paginator
    productos = Producto.objects.filter(se_vende_al_mayor=True).select_related('categoria').order_by('nombre')
    
    q = request.GET.get('q', '')
    cat_id = request.GET.get('categoria', '')
    
    if q:
        productos = productos.filter(nombre__icontains=q)
    if cat_id:
        productos = productos.filter(categoria_id=cat_id)
        
    paginator = Paginator(productos, 25)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    categorias = Categoria.objects.all()
    
    return render(request, 'inventario/productos_mayor_list.html', {
        'page_obj': page_obj,
        'productos': page_obj.object_list,
        'categorias': categorias,
        'q': q,
        'cat_id': cat_id
    })

@cajero_gerente_required
def ventas_mayor_list_view(request):
    from django.core.paginator import Paginator
    ventas = VentaMayor.objects.all().order_by('-fecha')
    paginator = Paginator(ventas, 50)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    productos = Producto.objects.filter(se_vende_al_mayor=True, cantidad_en_almacen__gt=0).order_by('nombre')
    
    return render(request, 'inventario/ventas_mayor_list.html', {
        'page_obj': page_obj,
        'ventas': page_obj.object_list,
        'productos': productos
    })

import json
@cajero_gerente_required
def venta_mayor_create_view(request):
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            cliente = data.get('cliente', '')
            items = data.get('items', [])
            
            if not cliente or not items:
                return JsonResponse({'success': False, 'error': 'Faltan datos'})
                
            total = Decimal('0.00')
            with transaction.atomic():
                is_credito = data.get('es_credito', False)
                venta = VentaMayor.objects.create(
                    cliente=cliente, 
                    usuario=request.user if request.user.is_authenticated else None,
                    es_credito=is_credito,
                    pagado=not is_credito
                )
                
                global_metodo_pago = data.get('metodo_pago', 'EFECTIVO')
                for item in items:
                    producto = get_object_or_404(Producto, pk=item['id'])
                    cantidad = int(item['cantidad'])
                    
                    origen = item.get('origen', 'ALMACEN')
                    metodo_pago = global_metodo_pago
                    
                    # Descontar según el origen
                    if origen == 'ALMACEN':
                        if producto.cantidad_en_almacen >= cantidad:
                            producto.cantidad_en_almacen -= cantidad
                            producto.save()
                            MovimientoInventario.objects.create(producto=producto, usuario=request.user if request.user.is_authenticated else None, tipo='SALIDA', ubicacion='ALMACEN', cantidad=cantidad, motivo=f'Venta al mayor #{venta.id}', stock_resultante=producto.cantidad_en_almacen)
                        else:
                            raise ValueError(f'Stock insuficiente en almacén para {producto.nombre}')
                    else:
                        if producto.cantidad_en_tienda >= cantidad:
                            producto.cantidad_en_tienda -= cantidad
                            producto.save()
                            MovimientoInventario.objects.create(producto=producto, usuario=request.user if request.user.is_authenticated else None, tipo='SALIDA', ubicacion='TIENDA', cantidad=cantidad, motivo=f'Venta al mayor #{venta.id}', stock_resultante=producto.cantidad_en_tienda)
                        else:
                            raise ValueError(f'Stock insuficiente en tienda para {producto.nombre}')
                    
                    if metodo_pago == 'EFECTIVO':
                        precio = producto.precio_venta_mayor_usd_efectivo or Decimal('0')
                    else:
                        precio = producto.precio_venta_mayor_usd_bcv or Decimal('0')
                        
                    subtotal = precio * cantidad
                    total += subtotal
                    
                    DetalleVentaMayor.objects.create(
                        venta=venta,
                        producto=producto,
                        cantidad=cantidad,
                        metodo_pago=metodo_pago,
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

@cajero_gerente_required
def creditos_list_view(request):
    from django.db.models import Sum
    creditos = VentaMayor.objects.filter(es_credito=True, pagado=False).order_by('-fecha')
    
    creditos_data = []
    for c in creditos:
        abonado = c.abonos.aggregate(total=Sum('monto_usd'))['total'] or Decimal('0.00')
        restante = c.total_usd - abonado
        if restante <= 0:
            c.pagado = True
            c.save()
        else:
            creditos_data.append({
                'venta': c,
                'abonado': abonado,
                'restante': restante
            })
            
    return render(request, 'inventario/creditos_list.html', {'creditos_data': creditos_data})

@cajero_gerente_required
def abono_credito_view(request, pk):
    if request.method == 'POST':
        from django.db.models import Sum
        venta = get_object_or_404(VentaMayor, pk=pk)
        try:
            monto = Decimal(request.POST.get('monto_usd', '0'))
            nota = request.POST.get('nota', '')
            
            if monto > 0:
                AbonoCredito.objects.create(
                    venta=venta,
                    monto_usd=monto,
                    nota=nota,
                    usuario=request.user if request.user.is_authenticated else None
                )
                
                abonado = venta.abonos.aggregate(total=Sum('monto_usd'))['total'] or Decimal('0.00')
                if abonado >= venta.total_usd:
                    venta.pagado = True
                    venta.save()
                    messages.success(request, f'Crédito de la factura #{venta.id} pagado en su totalidad.')
                else:
                    messages.success(request, f'Abono de ${monto} registrado exitosamente.')
        except Exception as e:
            messages.error(request, f'Error al procesar el abono: {str(e)}')
                
    return redirect('inventario:creditos_list')

@cajero_gerente_required
def venta_mayor_export_pdf_view(request, pk):
    from reportlab.lib.pagesizes import letter
    from reportlab.lib import colors
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, Image
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from django.http import HttpResponse
    import os
    from django.conf import settings
    
    venta = get_object_or_404(VentaMayor, pk=pk)
    
    response = HttpResponse(content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="factura_mayor_{venta.id}.pdf"'
    
    doc = SimpleDocTemplate(response, pagesize=letter, rightMargin=30, leftMargin=30, topMargin=30, bottomMargin=18)
    elements = []
    styles = getSampleStyleSheet()
    
    # Custom styles
    title_style = ParagraphStyle(
        name='MainTitle',
        parent=styles['Title'],
        fontSize=24,
        textColor=colors.HexColor('#6c5ce7'),
        spaceAfter=10,
        alignment=0 # Left
    )
    
    info_style = ParagraphStyle(
        name='Info',
        parent=styles['Normal'],
        fontSize=11,
        textColor=colors.HexColor('#4a4a4a'),
        spaceAfter=4
    )
    
    logo_path = os.path.join(settings.BASE_DIR, 'inventario', 'static', 'inventario', 'img', 'logo.jpg')
    
    header_table_data = []
    factura_info = Paragraph(f"<b>FACTURA #{venta.id:05d}</b><br/>Fecha: {venta.fecha.strftime('%d/%m/%Y %H:%M')}", styles['Normal'])
    
    if os.path.exists(logo_path):
        logo = Image(logo_path, width=100, height=100)
        header_table_data.append([logo, factura_info])
    else:
        header_table_data.append([Paragraph("ThorCore", title_style), factura_info])
        
    header_table = Table(header_table_data, colWidths=[270, 270])
    header_table.setStyle(TableStyle([
        ('ALIGN', (1, 0), (1, 0), 'RIGHT'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 20),
    ]))
    elements.append(header_table)
    
    # Cliente Info
    elements.append(Paragraph(f"<b>Facturado a:</b>", styles['Heading3']))
    elements.append(Paragraph(f"Cliente: <b>{venta.cliente}</b>", info_style))
    elements.append(Spacer(1, 20))
    
    # Tabla
    data = [['Producto', 'Cant', 'Método Pago', 'Precio Unit.', 'Subtotal']]
    for detalle in venta.detalles.all():
        metodo = 'Efectivo ($)' if detalle.metodo_pago == 'EFECTIVO' else 'Dólares a BCV'
        data.append([
            detalle.producto.nombre,
            str(detalle.cantidad),
            metodo,
            f"${detalle.precio_unitario_usd:.2f}",
            f"${detalle.subtotal_usd:.2f}"
        ])
        
    data.append(['', '', '', 'TOTAL A PAGAR:', f"${venta.total_usd:.2f}"])
    
    t = Table(data, colWidths=[200, 50, 100, 90, 100])
    t.setStyle(TableStyle([
        # Encabezado tabla
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#6c5ce7')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('ALIGN', (0, 0), (-1, 0), 'CENTER'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('PADDING', (0, 0), (-1, 0), 10),
        
        # Cuerpo tabla
        ('ALIGN', (1, 1), (-1, -1), 'CENTER'),
        ('BACKGROUND', (0, 1), (-1, -2), colors.HexColor('#f8f9fa')),
        ('GRID', (0, 0), (-1, -2), 0.5, colors.HexColor('#dcdde1')),
        ('PADDING', (0, 1), (-1, -1), 8),
        
        # Fila TOTAL
        ('FONTNAME', (3, -1), (4, -1), 'Helvetica-Bold'),
        ('TEXTCOLOR', (4, -1), (4, -1), colors.HexColor('#00b894')),
        ('ALIGN', (3, -1), (3, -1), 'RIGHT'),
        ('BACKGROUND', (0, -1), (-1, -1), colors.white),
        ('LINEABOVE', (3, -1), (4, -1), 1.5, colors.HexColor('#6c5ce7')),
        ('PADDING', (3, -1), (4, -1), 12),
    ]))
    
    elements.append(t)
    
    # Pie de página
    elements.append(Spacer(1, 40))
    elements.append(Paragraph("¡Gracias por su compra en ThorCore!", ParagraphStyle(name='Footer', alignment=1, textColor=colors.HexColor('#a4b0be'))))
    
    doc.build(elements)
    
    return response

@cajero_gerente_required
def venta_detal_create_view(request):
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            cliente = data.get('cliente', '')
            items = data.get('items', [])
            
            if not items:
                return JsonResponse({'success': False, 'error': 'Faltan datos'})
                
            total = Decimal('0.00')
            with transaction.atomic():
                venta = VentaDetal.objects.create(cliente=cliente, usuario=request.user if request.user.is_authenticated else None)
                
                for item in items:
                    producto = get_object_or_404(Producto, pk=item['id'])
                    cantidad = Decimal(str(item['cantidad']))
                    
                    if producto.cantidad_en_tienda >= cantidad:
                        producto.cantidad_en_tienda -= cantidad
                        producto.save()
                        MovimientoInventario.objects.create(
                            producto=producto, 
                            usuario=request.user if request.user.is_authenticated else None, 
                            tipo='SALIDA', 
                            ubicacion='TIENDA', 
                            cantidad=cantidad, 
                            motivo=f'Venta al detal #{venta.id}', 
                            stock_resultante=producto.cantidad_en_tienda
                        )
                    else:
                        raise ValueError(f'Stock insuficiente en tienda para {producto.nombre}')
                    
                    # Para venta al detal usamos el precio por porción
                    precio_porcion = producto.precio_venta_detal_porcion or producto.precio_venta_publico
                    if not precio_porcion:
                        raise ValueError(f'El producto {producto.nombre} no tiene un precio de venta configurado')
                    
                    # Como precio_porcion está en VES o USD (moneda_venta), y total_usd asume que el total es en USD, necesitamos unificar
                    # O guardar total_ves o convertir a USD si moneda_venta es VES
                    if producto.moneda_venta == 'VES':
                        rates = get_cached_rates()
                        tasa_bcv = rates.get('BCV').tasa_margen if 'BCV' in rates else Decimal('1')
                        precio_usd = precio_porcion / tasa_bcv if tasa_bcv > 0 else Decimal('0')
                    else:
                        precio_usd = precio_porcion

                    subtotal_usd = precio_usd * cantidad
                    total += subtotal_usd
                    
                    DetalleVentaDetal.objects.create(
                        venta=venta,
                        producto=producto,
                        cantidad=cantidad,
                        precio_unitario_usd=precio_usd,
                        subtotal_usd=subtotal_usd
                    )
                    
                venta.total_usd = total
                venta.save()
                
            return JsonResponse({'success': True, 'venta_id': venta.id})
        except Exception as e:
            return JsonResponse({'success': False, 'error': str(e)})
            
    productos = Producto.objects.filter(cantidad_en_tienda__gt=0).order_by('nombre')
    return render(request, 'inventario/venta_detal_create.html', {'productos': productos})

@gerente_required
def tasas_list_view(request):
    tasas = TasaCambio.objects.all()
    return render(request, 'inventario/tasas_list.html', {'tasas': tasas})

@gerente_required
def tasa_edit_view(request, pk):
    tasa = get_object_or_404(TasaCambio, pk=pk)
    config = ConfiguracionNegocio.objects.first()
    
    if request.method == 'POST':
        # Read fields directly
        new_moneda = request.POST.get('moneda', '').strip()
        new_referencia = request.POST.get('referencia', '').strip()
        tasa_real_str = request.POST.get('tasa_real')
        tasa_margen_str = request.POST.get('tasa_margen')
        
        if not tasa_real_str or not tasa_margen_str:
            return JsonResponse({'success': False, 'errors': 'Faltan campos'})
            
        tasa_real = Decimal(tasa_real_str.replace(',', '.'))
        tasa_margen = Decimal(tasa_margen_str.replace(',', '.'))
        
        # Build the new ID if not BCV or USDT_VES
        if tasa.moneda in ['BCV', 'USDT_VES']:
            new_moneda_id = tasa.moneda
        else:
            if new_referencia:
                new_moneda_id = f"{new_moneda.upper()}_{new_referencia}"
            else:
                new_moneda_id = new_moneda.upper()
                
        # Check if ID changed
        if new_moneda_id != tasa.moneda:
            # Check if new ID already exists
            if TasaCambio.objects.filter(moneda=new_moneda_id).exists():
                return JsonResponse({'success': False, 'errors': 'Ya existe una tasa con ese nombre'})
            
            # Create new, update references, delete old
            nueva_tasa = TasaCambio.objects.create(
                moneda=new_moneda_id,
                tasa_real=tasa_real,
                tasa_margen=tasa_margen
            )
            Producto.objects.filter(moneda_compra=tasa.moneda).update(moneda_compra=new_moneda_id)
            tasa.delete()
            tasa = nueva_tasa
        else:
            tasa.tasa_real = tasa_real
            tasa.tasa_margen = tasa_margen
            tasa.save()
            
        if tasa.moneda == 'BCV' and config:
            config.aumento_bcv_activo = request.POST.get('aumento_bcv_activo') == 'true'
            config.tipo_aumento_bcv = request.POST.get('tipo_aumento_bcv', config.tipo_aumento_bcv)
            config.valor_aumento_bcv = request.POST.get('valor_aumento_bcv', config.valor_aumento_bcv)
            config.save()
        elif tasa.moneda == 'USDT_VES' and config:
            config.aumento_usdt_activo = request.POST.get('aumento_usdt_activo') == 'true'
            config.tipo_aumento_usdt = request.POST.get('tipo_aumento_usdt', config.tipo_aumento_usdt)
            config.valor_aumento_usdt = request.POST.get('valor_aumento_usdt', config.valor_aumento_usdt)
            config.save()
            
        return JsonResponse({'success': True})
    
    return JsonResponse({'success': False, 'error': 'Método no permitido'})

@gerente_required
def tasa_delete_view(request, pk):
    if request.method == 'POST':
        tasa = get_object_or_404(TasaCambio, pk=pk)
        if tasa.moneda not in ['BCV', 'USDT_VES']:
            # Fallback products using this rate to USD
            Producto.objects.filter(moneda_compra=tasa.moneda).update(moneda_compra='USD')
            tasa.delete()
            messages.success(request, 'Tasa eliminada correctamente.')
        else:
            messages.error(request, 'No se pueden eliminar las tasas principales del sistema.')
    return redirect('inventario:centro_control')

@gerente_required
def tasa_create_view(request):
    if request.method == 'POST':
        moneda = request.POST.get('moneda', '').strip()
        referencia = request.POST.get('referencia', '').strip()
        tasa_real = request.POST.get('tasa_real')
        tasa_margen = request.POST.get('tasa_margen')
        
        if not moneda or not tasa_real or not tasa_margen:
            return JsonResponse({'success': False, 'errors': 'Faltan campos requeridos'})
            
        if referencia:
            moneda_id = f"{moneda.upper()}_{referencia}"
        else:
            moneda_id = moneda.upper()
            
        try:
            TasaCambio.objects.create(
                moneda=moneda_id,
                tasa_real=Decimal(tasa_real.replace(',', '.')),
                tasa_margen=Decimal(tasa_margen.replace(',', '.'))
            )
            return JsonResponse({'success': True})
        except Exception as e:
            return JsonResponse({'success': False, 'errors': str(e)})
            
    return JsonResponse({'success': False, 'error': 'Invalid request'})

@gerente_required
def scrape_bcv_view(request):
    from .utils import scrape_bcv_rate, scrape_binance_usdt
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
            messages.success(request, f'Tasa BCV sincronizada ({rate:.2f}). Tu margen actual ({tasa_obj.tasa_margen:.2f}) se mantiene porque el BCV no lo superó.')
        else:
            config = ConfiguracionNegocio.objects.first()
            if not config:
                config = ConfiguracionNegocio.objects.create()
                
            tasa_obj.tasa_real = rate
            
            if config.aumento_bcv_activo:
                if config.tipo_aumento_bcv == 'PORCENTAJE':
                    nuevo_margen = rate * (Decimal('1') + (config.valor_aumento_bcv / Decimal('100')))
                    tasa_obj.tasa_margen = round(nuevo_margen, 2)
                    tasa_obj.save()
                    messages.success(request, f'Tasa BCV subió a {rate:.2f}. Margen actualizado a {tasa_obj.tasa_margen:.2f} (+{config.valor_aumento_bcv:.2f}%).')
                elif config.tipo_aumento_bcv == 'FIJO':
                    nuevo_margen = rate + config.valor_aumento_bcv
                    tasa_obj.tasa_margen = round(nuevo_margen, 2)
                    tasa_obj.save()
                    messages.success(request, f'Tasa BCV subió a {rate:.2f}. Margen actualizado a {tasa_obj.tasa_margen:.2f} (+{config.valor_aumento_bcv:.2f} Bs).')
                elif config.tipo_aumento_bcv == 'MANUAL':
                    tasa_obj.save() 
                    messages.warning(request, f'¡Alerta! BCV subió a {rate:.2f} y superó tu margen actual ({tasa_obj.tasa_margen:.2f}). Como estás en modo manual, el margen no se actualizó automáticamente.')
            else:
                tasa_obj.save()
                messages.warning(request, f'¡Alerta! BCV subió a {rate:.2f} y superó tu margen actual ({tasa_obj.tasa_margen:.2f}). Aumento automático desactivado.')
                
    # Binance USDT scraping
    usdt_rate, usdt_err = scrape_binance_usdt()
    if usdt_err:
        messages.error(request, usdt_err)
    elif usdt_rate:
        tasa_usdt_obj, _ = TasaCambio.objects.get_or_create(
            moneda='USDT_VES', 
            defaults={'tasa_real': usdt_rate, 'tasa_margen': usdt_rate}
        )
        
        if usdt_rate <= tasa_usdt_obj.tasa_margen:
            tasa_usdt_obj.tasa_real = usdt_rate
            tasa_usdt_obj.save()
            messages.success(request, f'Tasa USDT sincronizada ({usdt_rate}). Tu margen actual ({tasa_usdt_obj.tasa_margen}) se mantiene.')
        else:
            config = ConfiguracionNegocio.objects.first()
            if not config:
                config = ConfiguracionNegocio.objects.create()
                
            tasa_usdt_obj.tasa_real = usdt_rate
            
            if config.aumento_usdt_activo:
                if config.tipo_aumento_usdt == 'PORCENTAJE':
                    nuevo_margen = usdt_rate * (Decimal('1') + (config.valor_aumento_usdt / Decimal('100')))
                    tasa_usdt_obj.tasa_margen = round(nuevo_margen, 2)
                    tasa_usdt_obj.save()
                    messages.success(request, f'Tasa USDT subió a {usdt_rate}. Margen actualizado a {tasa_usdt_obj.tasa_margen} (+{config.valor_aumento_usdt}%).')
                elif config.tipo_aumento_usdt == 'FIJO':
                    nuevo_margen = usdt_rate + config.valor_aumento_usdt
                    tasa_usdt_obj.tasa_margen = round(nuevo_margen, 2)
                    tasa_usdt_obj.save()
                    messages.success(request, f'Tasa USDT subió a {usdt_rate}. Margen actualizado a {tasa_usdt_obj.tasa_margen} (+{config.valor_aumento_usdt} Bs).')
                elif config.tipo_aumento_usdt == 'MANUAL':
                    tasa_usdt_obj.save()
                    messages.warning(request, f'¡Alerta! USDT subió a {usdt_rate} y superó tu margen. Como estás en modo manual, el margen no se actualizó automáticamente.')
            else:
                tasa_usdt_obj.save()
                messages.warning(request, f'¡Alerta! USDT subió a {usdt_rate} y superó tu margen actual ({tasa_usdt_obj.tasa_margen}). Aumento automático desactivado.')

    return redirect('inventario:centro_control')

@gerente_required
def kardex_list_view(request):
    from django.core.paginator import Paginator
    from .models import MovimientoInventario
    from datetime import datetime, time
    from django.utils.timezone import make_aware
    
    movimientos = MovimientoInventario.objects.select_related('producto', 'usuario').all().order_by('-fecha')
    
    q = request.GET.get('q', '')
    fecha_inicio = request.GET.get('fecha_inicio', '')
    fecha_fin = request.GET.get('fecha_fin', '')
    
    if q:
        movimientos = movimientos.filter(producto__nombre__icontains=q)
        
    if fecha_inicio:
        try:
            fi = make_aware(datetime.strptime(fecha_inicio, '%Y-%m-%d'))
            movimientos = movimientos.filter(fecha__gte=fi)
        except ValueError:
            pass
            
    if fecha_fin:
        try:
            ff = make_aware(datetime.combine(datetime.strptime(fecha_fin, '%Y-%m-%d'), time.max))
            movimientos = movimientos.filter(fecha__lte=ff)
        except ValueError:
            pass
            
    paginator = Paginator(movimientos, 50)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    return render(request, 'inventario/kardex_list.html', {
        'page_obj': page_obj, 
        'q': q, 
        'fecha_inicio': fecha_inicio, 
        'fecha_fin': fecha_fin
    })

@gerente_required
def categoria_list_view(request):
    categorias = Categoria.objects.all().order_by('nombre')
    return render(request, 'inventario/categorias_list.html', {'categorias': categorias})

@gerente_required
def centro_control_view(request):
    categorias = Categoria.objects.all().order_by('nombre')
    tasas = TasaCambio.objects.all()
    metodos_pago = MetodoPago.objects.all().order_by('nombre')
    config = ConfiguracionNegocio.objects.first()
    if not config:
        config = ConfiguracionNegocio.objects.create()
        
    return render(request, 'inventario/centro_control.html', {'categorias': categorias, 'tasas': tasas, 'config': config, 'metodos_pago': metodos_pago})

@gerente_required
def update_configuracion_view(request):
    if request.method == 'POST':
        config = ConfiguracionNegocio.objects.first()
        if not config:
            config = ConfiguracionNegocio.objects.create()
            
        import json
        is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest' or request.content_type == 'application/json'
        
        if is_ajax and request.body:
            try:
                data = json.loads(request.body)
                if 'redondear_usd' in data: config.redondear_usd = data['redondear_usd']
                if 'redondear_ves' in data: config.redondear_ves = data['redondear_ves']
                if 'valor_redondeo_usd' in data: config.valor_redondeo_usd = data['valor_redondeo_usd']
                if 'valor_redondeo_ves' in data: config.valor_redondeo_ves = data['valor_redondeo_ves']
                config.save()
                return JsonResponse({'success': True, 'message': 'Configuración guardada.'})
            except Exception as e:
                return JsonResponse({'success': False, 'error': str(e)})
            
        # Fallback normal POST
        redondear_usd = request.POST.get('redondear_usd') == 'on'
        redondear_ves = request.POST.get('redondear_ves') == 'on'
        
        try:
            val_usd = request.POST.get('valor_redondeo_usd')
            if val_usd: config.valor_redondeo_usd = val_usd
            val_ves = request.POST.get('valor_redondeo_ves')
            if val_ves: config.valor_redondeo_ves = val_ves
        except Exception:
            pass
            
        config.redondear_usd = redondear_usd
        config.redondear_ves = redondear_ves
        config.save()
        messages.success(request, 'Configuración de redondeo actualizada con éxito.')
    return redirect('inventario:centro_control')

@gerente_required
def categoria_create_view(request):
    if request.method == 'POST':
        form = CategoriaForm(request.POST)
        if form.is_valid():
            form.save()
            if request.headers.get('x-requested-with') == 'XMLHttpRequest':
                return JsonResponse({'success': True})
            messages.success(request, 'Categoría creada con éxito.')
            return redirect('inventario:centro_control')
        else:
            if request.headers.get('x-requested-with') == 'XMLHttpRequest':
                return JsonResponse({'success': False, 'errors': form.errors})
    else:
        form = CategoriaForm()
    return render(request, 'inventario/formulario_generico.html', {
        'form': form,
        'title': 'Nueva Categoría',
        'button_text': 'Guardar',
        'back_url': 'inventario:centro_control'
    })

@gerente_required
def categoria_edit_view(request, pk):
    categoria = get_object_or_404(Categoria, pk=pk)
    if request.method == 'POST':
        form = CategoriaForm(request.POST, instance=categoria)
        if form.is_valid():
            form.save()
            if request.headers.get('x-requested-with') == 'XMLHttpRequest':
                return JsonResponse({'success': True})
            messages.success(request, 'Categoría actualizada.')
            return redirect('inventario:centro_control')
        else:
            if request.headers.get('x-requested-with') == 'XMLHttpRequest':
                return JsonResponse({'success': False, 'errors': form.errors})
    else:
        form = CategoriaForm(instance=categoria)
    return render(request, 'inventario/formulario_generico.html', {
        'form': form,
        'title': f'Editar Categoría: {categoria.nombre}',
        'button_text': 'Actualizar',
        'back_url': 'inventario:centro_control'
    })

@gerente_required
def categoria_delete_view(request, pk):
    categoria = get_object_or_404(Categoria, pk=pk)
    if request.method == 'POST':
        categoria.delete()
        messages.success(request, 'Categoría eliminada con éxito.')
        return redirect('inventario:centro_control')
    return redirect('inventario:centro_control')

@gerente_required
def producto_export_pdf_view(request):
    productos = Producto.objects.select_related('categoria').all().order_by('nombre')
    q = request.GET.get('q', '')
    categoria_id = request.GET.get('categoria', '')
    
    if q:
        productos = productos.filter(nombre__icontains=q)
    if categoria_id:
        productos = productos.filter(categoria_id=categoria_id)
        
    from reportlab.lib.pagesizes import letter
    from reportlab.lib import colors
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, Image
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    import os
    from django.conf import settings
    
    response = HttpResponse(content_type='application/pdf')
    response['Content-Disposition'] = 'attachment; filename="Listado_Productos.pdf"'
    
    doc = SimpleDocTemplate(response, pagesize=letter, rightMargin=30, leftMargin=30, topMargin=30, bottomMargin=30)
    elements = []
    
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        name='MainTitle',
        parent=styles['Title'],
        fontSize=24,
        textColor=colors.HexColor('#6c5ce7'),
        spaceAfter=10,
        alignment=0 # Left
    )
    
    logo_path = os.path.join(settings.BASE_DIR, 'inventario', 'static', 'inventario', 'img', 'logo.jpg')
    
    header_table_data = []
    
    title_text = "Listado de Productos al Detal"
    if categoria_id:
        try:
            cat_nombre = Categoria.objects.get(id=categoria_id).nombre
            title_text += f" - {cat_nombre}"
        except:
            pass
            
    header_info = Paragraph(f"<b>{title_text}</b>", styles['Normal'])
    
    if os.path.exists(logo_path):
        logo = Image(logo_path, width=80, height=80)
        header_table_data.append([logo, header_info])
    else:
        header_table_data.append([Paragraph("ThorCore", title_style), header_info])
        
    header_table = Table(header_table_data, colWidths=[270, 270])
    header_table.setStyle(TableStyle([
        ('ALIGN', (1, 0), (1, 0), 'RIGHT'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 20),
    ]))
    elements.append(header_table)
    elements.append(Spacer(1, 12))
    
    # Agrupar por categoría
    categorias_dict = {}
    for p in productos:
        cat_name = p.categoria.nombre if p.categoria else 'Sin Categoría'
        if cat_name not in categorias_dict:
            categorias_dict[cat_name] = []
        categorias_dict[cat_name].append(p)
        
    for cat_name, prods in categorias_dict.items():
        elements.append(Paragraph(cat_name, styles['Heading2']))
        elements.append(Spacer(1, 6))
        
        data = [["ID", "Nombre", "Stock Alm.", "Stock Tda.", "PVP Porción"]]
        
        for p in prods:
            pvp_kg = "N/A"
            if p.precio_venta_detal_porcion:
                pvp_kg = f"{p.precio_venta_detal_porcion:.2f} {p.moneda_venta}"
                
            data.append([
                f"#{p.id}",
                p.nombre,
                str(p.cantidad_en_almacen),
                str(p.cantidad_en_tienda),
                pvp_kg
            ])
            
        table = Table(data, colWidths=[60, 240, 70, 70, 100])
        table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#6c5ce7')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('ALIGN', (0, 0), (-1, 0), 'CENTER'),
            ('ALIGN', (1, 0), (1, -1), 'LEFT'),
            ('ALIGN', (2, 1), (-1, -1), 'CENTER'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('PADDING', (0, 0), (-1, 0), 8),
            ('BACKGROUND', (0, 1), (-1, -1), colors.HexColor('#f8f9fa')),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#dcdde1')),
            ('PADDING', (0, 1), (-1, -1), 6),
        ]))
        
        elements.append(table)
        elements.append(Spacer(1, 12))
        
    doc.build(elements)
    
    return response

@gerente_required
def producto_export_pdf_mayor_view(request):
    productos = Producto.objects.filter(se_vende_al_mayor=True).select_related('categoria').order_by('nombre')
    
    from reportlab.lib.pagesizes import letter
    from reportlab.lib import colors
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, Image
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    import os
    from django.conf import settings

    response = HttpResponse(content_type='application/pdf')
    response['Content-Disposition'] = 'attachment; filename="Listado_Mayoristas.pdf"'
    
    doc = SimpleDocTemplate(response, pagesize=letter, rightMargin=30, leftMargin=30, topMargin=30, bottomMargin=30)
    elements = []
    
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        name='MainTitle',
        parent=styles['Title'],
        fontSize=24,
        textColor=colors.HexColor('#6c5ce7'),
        spaceAfter=10,
        alignment=0 # Left
    )
    
    logo_path = os.path.join(settings.BASE_DIR, 'inventario', 'static', 'inventario', 'img', 'logo.jpg')
    
    header_table_data = []
    
    header_info = Paragraph("<b>Listado de Productos al Mayor</b>", styles['Normal'])
    
    if os.path.exists(logo_path):
        logo = Image(logo_path, width=80, height=80)
        header_table_data.append([logo, header_info])
    else:
        header_table_data.append([Paragraph("ThorCore", title_style), header_info])
        
    header_table = Table(header_table_data, colWidths=[270, 270])
    header_table.setStyle(TableStyle([
        ('ALIGN', (1, 0), (1, 0), 'RIGHT'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 20),
    ]))
    elements.append(header_table)
    elements.append(Spacer(1, 12))
    
    categorias_dict = {}
    for p in productos:
        cat_name = p.categoria.nombre if p.categoria else 'Sin Categoría'
        if cat_name not in categorias_dict:
            categorias_dict[cat_name] = []
        categorias_dict[cat_name].append(p)
        
    for cat_name, prods in categorias_dict.items():
        elements.append(Paragraph(cat_name, styles['Heading2']))
        elements.append(Spacer(1, 6))
        
        data = [["ID", "Nombre", "Stock Alm.", "PVP Mayor Efec ($)", "PVP Mayor BCV"]]
        
        for p in prods:
            pvp_usd_eff = f"{p.precio_venta_mayor_usd_efectivo} $" if p.precio_venta_mayor_usd_efectivo else "N/A"
            pvp_bs = f"{p.precio_venta_mayor_bcv} Bs" if p.precio_venta_mayor_bcv else "N/A"
                
            data.append([
                f"#{p.id}",
                p.nombre,
                str(p.cantidad_en_almacen),
                pvp_usd_eff,
                pvp_bs
            ])
            
        table = Table(data, colWidths=[40, 200, 60, 120, 120])
        table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#6c5ce7')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('ALIGN', (0, 0), (-1, 0), 'CENTER'),
            ('ALIGN', (1, 0), (1, -1), 'LEFT'),
            ('ALIGN', (2, 1), (-1, -1), 'CENTER'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('PADDING', (0, 0), (-1, 0), 8),
            ('BACKGROUND', (0, 1), (-1, -1), colors.HexColor('#f8f9fa')),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#dcdde1')),
            ('PADDING', (0, 1), (-1, -1), 6),
        ]))
        
        elements.append(table)
        elements.append(Spacer(1, 12))
        
    doc.build(elements)
    
    return response
from django.db.models import DecimalField
from datetime import timedelta

@gerente_required
def dashboard_estadisticas_view(request):
    from django.db.models import Sum
    from datetime import datetime, timedelta
    
    tipo_filtro = request.GET.get('tipo', 'todos') # todos, mayor, detal
    tiempo_filtro = request.GET.get('tiempo', 'semana') # hoy, ayer, semana, mes, todos, custom
    top_limit = int(request.GET.get('top_limit', 5))
    start_date_str = request.GET.get('start_date')
    end_date_str = request.GET.get('end_date')
    
    today = timezone.now().date()
    
    # Determinar el rango de fechas
    if tiempo_filtro == 'custom' and start_date_str and end_date_str:
        start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date()
        end_date = datetime.strptime(end_date_str, '%Y-%m-%d').date()
        intervalo = 'diario'
    elif tiempo_filtro == '7dias':
        start_date = today - timedelta(days=6)
        end_date = today
        intervalo = 'diario'
    elif tiempo_filtro == '1mes':
        start_date = today - timedelta(days=30)
        end_date = today
        intervalo = 'diario'
    elif tiempo_filtro == '1ano':
        start_date = today - timedelta(days=365)
        end_date = today
        intervalo = 'diario'
    elif tiempo_filtro == 'semanal':
        start_date = today - timedelta(days=365) # Un año para la vista semanal por defecto
        end_date = today
        intervalo = 'semanal'
    elif tiempo_filtro == 'mensual':
        start_date = None
        end_date = today
        intervalo = 'mensual'
    elif tiempo_filtro == 'anual':
        start_date = None
        end_date = today
        intervalo = 'anual'
    else:
        start_date = today - timedelta(days=6)
        end_date = today
        intervalo = 'diario'
        
    # 1. Ventas por dia (Grafico)
    ventas_por_dia = []
    fechas = []
    
    chart_start = start_date if start_date else None
    
    if not chart_start:
        min_mayor = VentaMayor.objects.order_by('fecha').first()
        min_detal = VentaDetal.objects.order_by('fecha').first()
        d1 = min_mayor.fecha.date() if min_mayor else today
        d2 = min_detal.fecha.date() if min_detal else today
        chart_start = min(d1, d2)
        
    if chart_start > end_date:
        chart_start = end_date

    def get_date_range(d_start, d_end=None):
        from datetime import datetime, time
        from django.utils import timezone
        dt_start = timezone.make_aware(datetime.combine(d_start, time.min))
        if d_end:
            dt_end = timezone.make_aware(datetime.combine(d_end, time.max))
        else:
            dt_end = timezone.make_aware(datetime.combine(d_start, time.max))
        return dt_start, dt_end

    if intervalo == 'diario':
        chart_days = (end_date - chart_start).days + 1
        if chart_days > 366:
            chart_start = end_date - timedelta(days=365)
            chart_days = 366
        
        for i in range(chart_days):
            fecha = chart_start + timedelta(days=i)
            dt_start, dt_end = get_date_range(fecha)
            suma_mayor = Decimal('0.00')
            suma_detal = Decimal('0.00')
            if tipo_filtro in ['todos', 'mayor']:
                suma_mayor = VentaMayor.objects.filter(fecha__range=(dt_start, dt_end)).aggregate(total=Sum('total_usd'))['total'] or Decimal('0.00')
            if tipo_filtro in ['todos', 'detal']:
                suma_detal = VentaDetal.objects.filter(fecha__range=(dt_start, dt_end)).aggregate(total=Sum('total_usd'))['total'] or Decimal('0.00')
                
            fechas.append(fecha.strftime('%d %b'))
            ventas_por_dia.append(float(suma_mayor + suma_detal))

    elif intervalo == 'semanal':
        current_monday = chart_start - timedelta(days=chart_start.weekday())
        while current_monday <= end_date:
            next_monday = current_monday + timedelta(days=7)
            dt_start, dt_end = get_date_range(current_monday, next_monday - timedelta(days=1))
            suma_mayor = Decimal('0.00')
            suma_detal = Decimal('0.00')
            if tipo_filtro in ['todos', 'mayor']:
                suma_mayor = VentaMayor.objects.filter(fecha__range=(dt_start, dt_end)).aggregate(total=Sum('total_usd'))['total'] or Decimal('0.00')
            if tipo_filtro in ['todos', 'detal']:
                suma_detal = VentaDetal.objects.filter(fecha__range=(dt_start, dt_end)).aggregate(total=Sum('total_usd'))['total'] or Decimal('0.00')
                
            fechas.append(f"{current_monday.strftime('%d %b')} - {(next_monday - timedelta(days=1)).strftime('%d %b')}")
            ventas_por_dia.append(float(suma_mayor + suma_detal))
            current_monday = next_monday

    elif intervalo == 'mensual':
        current_month_start = chart_start.replace(day=1)
        while current_month_start <= end_date:
            if current_month_start.month == 12:
                next_month_start = current_month_start.replace(year=current_month_start.year+1, month=1)
            else:
                next_month_start = current_month_start.replace(month=current_month_start.month+1)
                
            dt_start, dt_end = get_date_range(current_month_start, next_month_start - timedelta(days=1))
            suma_mayor = Decimal('0.00')
            suma_detal = Decimal('0.00')
            if tipo_filtro in ['todos', 'mayor']:
                suma_mayor = VentaMayor.objects.filter(fecha__range=(dt_start, dt_end)).aggregate(total=Sum('total_usd'))['total'] or Decimal('0.00')
            if tipo_filtro in ['todos', 'detal']:
                suma_detal = VentaDetal.objects.filter(fecha__range=(dt_start, dt_end)).aggregate(total=Sum('total_usd'))['total'] or Decimal('0.00')
                
            fechas.append(current_month_start.strftime('%b %Y'))
            ventas_por_dia.append(float(suma_mayor + suma_detal))
            current_month_start = next_month_start

    elif intervalo == 'anual':
        current_year = chart_start.year
        while current_year <= end_date.year:
            year_start = chart_start.replace(year=current_year, month=1, day=1)
            year_end = chart_start.replace(year=current_year, month=12, day=31)
            dt_start, dt_end = get_date_range(year_start, year_end)
            suma_mayor = Decimal('0.00')
            suma_detal = Decimal('0.00')
            if tipo_filtro in ['todos', 'mayor']:
                suma_mayor = VentaMayor.objects.filter(fecha__range=(dt_start, dt_end)).aggregate(total=Sum('total_usd'))['total'] or Decimal('0.00')
            if tipo_filtro in ['todos', 'detal']:
                suma_detal = VentaDetal.objects.filter(fecha__range=(dt_start, dt_end)).aggregate(total=Sum('total_usd'))['total'] or Decimal('0.00')
                
            fechas.append(str(current_year))
            ventas_por_dia.append(float(suma_mayor + suma_detal))
            current_year += 1
        
    # Aplicar filtros a Querysets
    detalles_mayor = DetalleVentaMayor.objects.all()
    detalles_detal = DetalleVentaDetal.objects.all()
    cierres_q = CierreDiario.objects.all()
    
    if start_date:
        dt_start, dt_end = get_date_range(start_date, end_date)
        detalles_mayor = detalles_mayor.filter(venta__fecha__range=(dt_start, dt_end))
        detalles_detal = detalles_detal.filter(venta__fecha__range=(dt_start, dt_end))
        cierres_q = cierres_q.filter(fecha__gte=start_date, fecha__lte=end_date)
        
    # Top Productos
    top_productos = []
    try:
        dict_productos = {}
        if tipo_filtro in ['todos', 'mayor']:
            for d in detalles_mayor.values('producto__nombre').annotate(total_cant=Sum('cantidad')):
                dict_productos[d['producto__nombre']] = dict_productos.get(d['producto__nombre'], 0) + float(d['total_cant'])
                
        if tipo_filtro in ['todos', 'detal']:
            for d in detalles_detal.values('producto__nombre').annotate(total_cant=Sum('cantidad')):
                dict_productos[d['producto__nombre']] = dict_productos.get(d['producto__nombre'], 0) + float(d['total_cant'])
                
        sorted_prods = sorted(dict_productos.items(), key=lambda x: x[1], reverse=True)[:top_limit]
        top_productos = [{'nombre': k, 'cantidad': v} for k, v in sorted_prods]
    except Exception as e:
        pass
        
    producto_mas_sale = top_productos[0]['nombre'] if top_productos else "Sin datos"
    
    # Estadísticas de Cierres
    cierre_total = cierres_q.aggregate(total=Sum('total_usd'))['total'] or Decimal('0.00')
    mejor_dia_cierre = cierres_q.order_by('-total_usd').first()
    dia_mas_cierre = mejor_dia_cierre.fecha.strftime('%d %b %Y') if mejor_dia_cierre else "Sin datos"
    monto_mejor_cierre = mejor_dia_cierre.total_usd if mejor_dia_cierre else Decimal('0.00')

    context = {
        'fechas_chart': fechas,
        'ventas_chart': ventas_por_dia,
        'producto_mas_sale': producto_mas_sale,
        'top_productos': top_productos,
        'tipo_filtro': tipo_filtro,
        'tiempo_filtro': tiempo_filtro,
        
        'cierre_total': float(cierre_total),
        'dia_mas_cierre': dia_mas_cierre,
        'monto_mejor_cierre': float(monto_mejor_cierre),
    }
    
    if request.headers.get('x-requested-with') == 'XMLHttpRequest':
        return JsonResponse(context)
    
    return render(request, 'inventario/estadisticas.html', context)


@gerente_required
def metodo_pago_create_view(request):
    if request.method == 'POST':
        form = MetodoPagoForm(request.POST)
        if form.is_valid():
            form.save()
            if request.headers.get('x-requested-with') == 'XMLHttpRequest':
                return JsonResponse({'success': True})
            messages.success(request, 'Método de pago creado con éxito.')
            return redirect('inventario:centro_control')
        else:
            if request.headers.get('x-requested-with') == 'XMLHttpRequest':
                return JsonResponse({'success': False, 'errors': form.errors})
    return redirect('inventario:centro_control')

@gerente_required
def metodo_pago_edit_view(request, pk):
    metodo = get_object_or_404(MetodoPago, pk=pk)
    if request.method == 'POST':
        form = MetodoPagoForm(request.POST, instance=metodo)
        if form.is_valid():
            form.save()
            if request.headers.get('x-requested-with') == 'XMLHttpRequest':
                return JsonResponse({'success': True})
            messages.success(request, 'Método de pago actualizado.')
            return redirect('inventario:centro_control')
        else:
            if request.headers.get('x-requested-with') == 'XMLHttpRequest':
                return JsonResponse({'success': False, 'errors': form.errors})
    return redirect('inventario:centro_control')

@gerente_required
def metodo_pago_delete_view(request, pk):
    metodo = get_object_or_404(MetodoPago, pk=pk)
    if request.method == 'POST':
        try:
            metodo.delete()
            messages.success(request, 'Método de pago eliminado.')
        except Exception as e:
            messages.error(request, 'No se puede eliminar porque está en uso.')
    return redirect('inventario:centro_control')

@cajero_gerente_required
def cierre_list_view(request):
    from django.core.paginator import Paginator
    cierres = CierreDiario.objects.all().order_by('-fecha')
    paginator = Paginator(cierres, 50)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    metodos = MetodoPago.objects.filter(activo=True).order_by('nombre')
    tasa_bcv = TasaCambio.objects.filter(moneda='BCV').first()
    
    context = {
        'page_obj': page_obj,
        'metodos_pago': metodos,
        'tasa_bcv': tasa_bcv
    }
    return render(request, 'inventario/cierre_list.html', context)

import json
@cajero_gerente_required
def cierre_create_view(request):
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            fecha = data.get('fecha')
            detalles = data.get('detalles', [])
            
            if not fecha:
                return JsonResponse({'success': False, 'error': 'Falta la fecha del cierre'})
                
            total_usd = Decimal('0.00')
            with transaction.atomic():
                cierre, created = CierreDiario.objects.get_or_create(
                    fecha=fecha,
                    defaults={'usuario': request.user if request.user.is_authenticated else None}
                )
                
                if not created:
                    days_diff = (timezone.now().date() - cierre.fecha).days
                    if days_diff > 3:
                        return JsonResponse({'success': False, 'error': 'No se puede editar un cierre con más de 3 días de antigüedad.'})
                    cierre.detalles.all().delete()
                    
                if created or cierre.tasa_bcv <= 0:
                    tasa_bcv_obj = TasaCambio.objects.filter(moneda='BCV').first()
                    tasa_bcv_val = tasa_bcv_obj.tasa_real if tasa_bcv_obj else Decimal('1')
                    cierre.tasa_bcv = tasa_bcv_val
                else:
                    tasa_bcv_val = cierre.tasa_bcv
                    
                for det in detalles:
                    metodo_id = det.get('metodo_id')
                    monto_ingresado = Decimal(str(det.get('monto_usd', '0')))
                    if monto_ingresado > 0:
                        metodo = get_object_or_404(MetodoPago, pk=metodo_id)
                        
                        if metodo.moneda == 'VES':
                            monto_usd = monto_ingresado / tasa_bcv_val if tasa_bcv_val > 0 else Decimal('0')
                        else:
                            monto_usd = monto_ingresado
                            
                        DetalleCierreDiario.objects.create(
                            cierre=cierre,
                            metodo_pago=metodo,
                            monto_original=monto_ingresado,
                            monto_usd=monto_usd
                        )
                        total_usd += monto_usd
                        
                cierre.total_usd = total_usd
                cierre.save()
                
            return JsonResponse({'success': True, 'cierre_id': cierre.id})
        except Exception as e:
            return JsonResponse({'success': False, 'error': str(e)})
            
    return redirect('inventario:cierre_list')
