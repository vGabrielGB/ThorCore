from PIL import Image

def make_transparent(input_path, output_path, tolerance=50):
    img = Image.open(input_path)
    img = img.convert("RGBA")
    data = img.getdata()
    
    new_data = []
    for item in data:
        # Check if the pixel is white-ish
        if item[0] > 255 - tolerance and item[1] > 255 - tolerance and item[2] > 255 - tolerance:
            new_data.append((255, 255, 255, 0)) # Transparent
        else:
            new_data.append(item)
            
    img.putdata(new_data)
    img.save(output_path, "PNG")

if __name__ == "__main__":
    input_file = r"C:\Users\vGabrielGB\.gemini\antigravity-ide\brain\917ddb9a-6f2e-4a25-bc10-bd43a19de96c\friendly_pitbull_logo_1788313774087.jpg"
    output_file = r"c:\Users\vGabrielGB\Desktop\Proyectos\agrothor\inventario\static\inventario\img\logo.png"
    make_transparent(input_file, output_file)
    print("Saved transparent PNG.")
