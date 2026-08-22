from django.urls import path
from . import views

app_name = 'inventario'

urlpatterns = [
    path('', views.dashboard_view, name='dashboard'),
    path('estadisticas/', views.dashboard_estadisticas_view, name='estadisticas'),
    
    # Productos
    path('productos/', views.producto_list_view, name='producto_list'),
    path('productos/exportar-pdf/', views.producto_export_pdf_view, name='producto_export_pdf'),
    path('productos/nuevo/', views.producto_create_view, name='producto_create'),
    path('productos/<int:pk>/editar/', views.producto_edit_view, name='producto_edit'),
    path('productos/<int:pk>/eliminar/', views.producto_delete_view, name='producto_delete'),
    path('productos/<int:pk>/actualizar-mayor/', views.producto_update_mayor_view, name='producto_update_mayor'),
    path('productos/<int:pk>/actualizar-stock/', views.producto_update_stock_view, name='producto_update_stock'),
    path('productos-mayor/', views.productos_mayor_list_view, name='productos_mayor_list'),
    path('productos-mayor/pdf/', views.producto_export_pdf_mayor_view, name='producto_export_pdf_mayor'),
    
    path('centro-control/', views.centro_control_view, name='centro_control'),
    path('centro-control/actualizar-config/', views.update_configuracion_view, name='update_configuracion'),
    path('categorias/', views.categoria_list_view, name='categoria_list'),
    path('categorias/nueva/', views.categoria_create_view, name='categoria_create'),
    path('categorias/<int:pk>/editar/', views.categoria_edit_view, name='categoria_edit'),
    path('categorias/<int:pk>/eliminar/', views.categoria_delete_view, name='categoria_delete'),
    
    path('centro-control/metodo-pago/nuevo/', views.metodo_pago_create_view, name='metodo_pago_create'),
    path('centro-control/metodo-pago/<int:pk>/editar/', views.metodo_pago_edit_view, name='metodo_pago_edit'),
    path('centro-control/metodo-pago/<int:pk>/eliminar/', views.metodo_pago_delete_view, name='metodo_pago_delete'),
    
    path('cierres/', views.cierre_list_view, name='cierre_list'),
    path('cierres/nuevo/', views.cierre_create_view, name='cierre_create'),
    
    path('kardex/', views.kardex_list_view, name='kardex_list'),
    
    # Ventas
    path('ventas/', views.ventas_list_view, name='ventas_list'),
    path('ventas/nueva/', views.venta_detal_create_view, name='venta_create'),
    path('ventas-mayor/', views.ventas_mayor_list_view, name='ventas_mayor_list'),
    path('ventas-mayor/nueva/', views.venta_mayor_create_view, name='venta_mayor_create'),
    path('ventas-mayor/<int:pk>/pdf/', views.venta_mayor_export_pdf_view, name='venta_mayor_export_pdf'),
    path('creditos/', views.creditos_list_view, name='creditos_list'),
    path('creditos/<int:pk>/abonar/', views.abono_credito_view, name='abono_credito'),
    
    # Tasas
    path('tasas/', views.tasas_list_view, name='tasas_list'),
    path('tasas/<str:pk>/editar/', views.tasa_edit_view, name='tasa_edit'),
    path('tasas/actualizar-bcv/', views.scrape_bcv_view, name='scrape_bcv'),
]
