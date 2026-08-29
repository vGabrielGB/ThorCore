from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect

def roles_required(*group_names):
    """
    Verifica que el usuario sea superusuario o pertenezca a uno de los grupos indicados.
    Si el usuario no está logueado, lo redirige al admin login.
    Si no tiene permisos, levanta un PermissionDenied (HTTP 403).
    """
    def check_group(user):
        if not user.is_authenticated:
            return False
        if user.is_superuser:
            return True
        if user.groups.filter(name__in=group_names).exists():
            return True
        return False

    def decorator(view_func):
        def _wrapped_view(request, *args, **kwargs):
            if not request.user.is_authenticated:
                return redirect(f'/login/?next={request.path}')
            
            if check_group(request.user):
                return view_func(request, *args, **kwargs)
            else:
                raise PermissionDenied("No tienes permisos para acceder a esta vista.")
        return _wrapped_view
    return decorator

# Alias comunes
# Vista permitida tanto para Cajero como para Gerente (y Superuser)
cajero_gerente_required = roles_required('Cajero', 'Gerente')

# Vista permitida solo para Gerente (y Superuser)
gerente_required = roles_required('Gerente')

# Vista permitida solo para Superuser
superuser_required = roles_required()
