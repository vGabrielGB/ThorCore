import random
from django.contrib.auth import authenticate, login, logout
from django.core.mail import send_mail
from django.conf import settings
from django.shortcuts import render, redirect
from django.contrib import messages
from django.contrib.auth.models import User

def custom_login_view(request):
    if request.user.is_authenticated:
        return redirect('inventario:dashboard')
        
    if request.method == 'POST':
        u = request.POST.get('username')
        p = request.POST.get('password')
        user = authenticate(request, username=u, password=p)
        if user is not None:
            # Generate 6 digit code
            code = str(random.randint(100000, 999999))
            request.session['2fa_code'] = code
            request.session['2fa_user_id'] = user.id
            
            # Send email
            if user.email:
                send_mail(
                    'Código de Verificación Agrothor',
                    f'Tu código de verificación para iniciar sesión es: {code}',
                    settings.EMAIL_HOST_USER if hasattr(settings, 'EMAIL_HOST_USER') else 'no-reply@agrothor.com',
                    [user.email],
                    fail_silently=False,
                )
            else:
                # If no email, just print it to console for development
                print(f"=== 2FA CODE FOR {user.username}: {code} ===")
                
            return redirect('inventario:verify_2fa')
        else:
            messages.error(request, "Usuario o contraseña incorrectos.")
            
    return render(request, 'inventario/login.html')

def verify_2fa_view(request):
    if request.user.is_authenticated:
        return redirect('inventario:dashboard')
        
    user_id = request.session.get('2fa_user_id')
    valid_code = request.session.get('2fa_code')
    
    if not user_id or not valid_code:
        messages.error(request, "Tu sesión de inicio expiró. Inicia sesión de nuevo.")
        return redirect('inventario:login')
        
    if request.method == 'POST':
        code_entered = request.POST.get('code')
        if code_entered == valid_code:
            user = User.objects.get(id=user_id)
            login(request, user)
            
            # Cleanup session
            del request.session['2fa_code']
            del request.session['2fa_user_id']
            
            return redirect('inventario:dashboard')
        else:
            messages.error(request, "Código incorrecto. Inténtalo de nuevo.")
            
    return render(request, 'inventario/verify_2fa.html')

def custom_logout_view(request):
    logout(request)
    return redirect('inventario:login')
