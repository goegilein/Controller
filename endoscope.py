import usb1

def list_usb_devices():
    with usb1.USBContext() as context:
        for device in context.getDeviceList(skip_on_error=True):
            try:
                product = device.getProduct()
            except usb1.USBError:
                product = "Unknown"
            print(f"Device: {product}")
            print(f"  Vendor ID: {hex(device.getVendorID())}")
            print(f"  Product ID: {hex(device.getProductID())}")
            print()

def find_camera(vendor_id, product_id):
    with usb1.USBContext() as context:
        for device in context.getDeviceList(skip_on_error=True):
            if device.getVendorID() == vendor_id and device.getProductID() == product_id:
                return device
    raise ValueError("Device not found")

def turn_off_leds(device):
    with device.open() as handle:
        # Send a control request to turn off the LEDs
        # Replace the requestType, request, value, and index with the correct values
        requestType = usb1.ENDPOINT_OUT | usb1.REQUEST_TYPE_VENDOR | usb1.RECIPIENT_DEVICE
        request = 0x01  # Placeholder request
        value = 0x00  # Placeholder value
        index = 0x00  # Placeholder index
        handle.controlWrite(requestType, request, value, index, b'')

if __name__ == "__main__":
    # List all USB devices
    list_usb_devices()

    # Replace with your camera's vendor ID and product ID
    vendor_id = 0xEB1A
    product_id = 0x299F

    try:
        camera = find_camera(vendor_id, product_id)
        turn_off_leds(camera)
        print("LEDs turned off")
    except Exception as e:
        print(f"Error: {e}")


    #USB\VID_EB1A&PID_299F&REV_0328&MI_00
    #USB\VID_EB1A&PID_299F&MI_00
