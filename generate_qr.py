import qrcode

# Replace this with your actual public URL
qr_url = "https://app.mygymlahore.com/add_customer?mode=qr"

# Generate QR code
qr = qrcode.QRCode(
    version=1,
    error_correction=qrcode.constants.ERROR_CORRECT_H,
    box_size=10,
    border=4,
)
qr.add_data(qr_url)
qr.make(fit=True)

img = qr.make_image(fill_color="#ff7300", back_color="white")  # Use your brand color if desired

# Save PNG file (choose your path)
img.save("static/qr_registration.png")

print("QR code saved as static/qr_registration.png")
