/*
 * itoken2.c — virtual Senselock "EliteIV" dongle (proper WDM PnP function driver).
 *
 * Root-enumerated FDO; registers device interface GUID {171638F7-...} so the
 * game's EL SDK finds it via SetupDi and CreateFile()s the device path.
 * All ioctls are answered STATUS_SUCCESS; the real response data comes from
 * the user-mode replay layer (multiDLL hooking kernel32!DeviceIoControl).
 */

#include <ntddk.h>

/* {171638F7-1EAD-4873-BA98-C966ABCF0142} */
static const GUID GUID_ITOKEN2_IFACE =
    { 0x171638f7, 0x1ead, 0x4873, { 0xba, 0x98, 0xc9, 0x66, 0xab, 0xcf, 0x01, 0x42 } };

/* Reference string appended to the interface path so it contains the game's
 * enumeration filter: \\?\ROOT#SYSTEM#0003#Vid_0471&Pid_485e#{171638F7-...} */
static const UNICODE_STRING IFACE_REF =
    RTL_CONSTANT_STRING(L"Vid_0471&Pid_485e");

typedef struct _DEVICE_EXT {
    PDEVICE_OBJECT Self;
    PDEVICE_OBJECT NextLower;
    UNICODE_STRING IfaceName;
    BOOLEAN        IfaceOn;
} DEVICE_EXT, *PDEVICE_EXT;

static PDEVICE_OBJECT g_LegacyDev;

static NTSTATUS
Complete(PIRP Irp, NTSTATUS status)
{
    Irp->IoStatus.Status = status;
    Irp->IoStatus.Information = 0;
    IoCompleteRequest(Irp, IO_NO_INCREMENT);
    return status;
}

static NTSTATUS
ItokDispatchSuccess(PDEVICE_OBJECT DeviceObject, PIRP Irp)
{
    UNREFERENCED_PARAMETER(DeviceObject);
    return Complete(Irp, STATUS_SUCCESS);
}

static NTSTATUS
ItokDispatchDeviceControl(PDEVICE_OBJECT DeviceObject, PIRP Irp)
{
    PIO_STACK_LOCATION sp = IoGetCurrentIrpStackLocation(Irp);
    ULONG code = sp->Parameters.DeviceIoControl.IoControlCode;
    UNREFERENCED_PARAMETER(DeviceObject);
    Irp->IoStatus.Status = STATUS_SUCCESS;
    Irp->IoStatus.Information = (code != 0) ? sp->Parameters.DeviceIoControl.OutputBufferLength : 0;
    IoCompleteRequest(Irp, IO_NO_INCREMENT);
    return STATUS_SUCCESS;
}

static NTSTATUS
ItokPnp(PDEVICE_OBJECT DeviceObject, PIRP Irp)
{
    PDEVICE_EXT ext = (PDEVICE_EXT)DeviceObject->DeviceExtension;
    PIO_STACK_LOCATION sp = IoGetCurrentIrpStackLocation(Irp);
    NTSTATUS status;

    switch (sp->MinorFunction) {
    case IRP_MN_START_DEVICE:
        IoSkipCurrentIrpStackLocation(Irp);
        status = IoCallDriver(ext->NextLower, Irp);
        if (NT_SUCCESS(status) && !ext->IfaceOn) {
            IoSetDeviceInterfaceState(&ext->IfaceName, TRUE);
            ext->IfaceOn = TRUE;
        }
        return status;

    case IRP_MN_REMOVE_DEVICE:
        if (ext->IfaceOn) {
            IoSetDeviceInterfaceState(&ext->IfaceName, FALSE);
            ext->IfaceOn = FALSE;
        }
        if (ext->IfaceName.Buffer)
            RtlFreeUnicodeString(&ext->IfaceName);
        IoSkipCurrentIrpStackLocation(Irp);
        status = IoCallDriver(ext->NextLower, Irp);
        IoDetachDevice(ext->NextLower);
        IoDeleteDevice(DeviceObject);
        return status;

    default:
        IoSkipCurrentIrpStackLocation(Irp);
        return IoCallDriver(ext->NextLower, Irp);
    }
}

static NTSTATUS
ItokAddDevice(PDRIVER_OBJECT DriverObject, PDEVICE_OBJECT PhysicalDeviceObject)
{
    NTSTATUS status;
    PDEVICE_OBJECT fdo;
    PDEVICE_EXT ext;

    UNREFERENCED_PARAMETER(DriverObject);

    status = IoCreateDevice(DriverObject, sizeof(DEVICE_EXT), NULL,
                            FILE_DEVICE_UNKNOWN, FILE_DEVICE_SECURE_OPEN, FALSE, &fdo);
    if (!NT_SUCCESS(status))
        return status;

    ext = (PDEVICE_EXT)fdo->DeviceExtension;
    RtlZeroMemory(ext, sizeof(DEVICE_EXT));
    ext->Self = fdo;
    ext->NextLower = IoAttachDeviceToDeviceStack(fdo, PhysicalDeviceObject);
    if (!ext->NextLower) {
        IoDeleteDevice(fdo);
        return STATUS_DEVICE_NOT_CONNECTED;
    }

    status = IoRegisterDeviceInterface(PhysicalDeviceObject, &GUID_ITOKEN2_IFACE, &IFACE_REF, &ext->IfaceName);
    if (!NT_SUCCESS(status)) {
        IoDetachDevice(ext->NextLower);
        IoDeleteDevice(fdo);
        return status;
    }

    fdo->Flags |= DO_POWER_PAGABLE;
    fdo->Flags &= ~DO_DEVICE_INITIALIZING;
    return STATUS_SUCCESS;
}

static VOID
ItokUnload(PDRIVER_OBJECT DriverObject)
{
    UNICODE_STRING linkName;
    UNREFERENCED_PARAMETER(DriverObject);

    RtlInitUnicodeString(&linkName, L"\\DosDevices\\ITOKEN2");
    IoDeleteSymbolicLink(&linkName);
    if (g_LegacyDev)
        IoDeleteDevice(g_LegacyDev);
}

NTSTATUS
DriverEntry(PDRIVER_OBJECT DriverObject, PUNICODE_STRING RegistryPath)
{
    ULONG i;
    UNICODE_STRING devName, linkName;
    NTSTATUS status;
    UNREFERENCED_PARAMETER(RegistryPath);

    for (i = 0; i <= IRP_MJ_MAXIMUM_FUNCTION; i++)
        DriverObject->MajorFunction[i] = ItokDispatchSuccess;

    DriverObject->MajorFunction[IRP_MJ_DEVICE_CONTROL] = ItokDispatchDeviceControl;
    DriverObject->MajorFunction[IRP_MJ_PNP] = ItokPnp;
    DriverObject->DriverExtension->AddDevice = ItokAddDevice;
    DriverObject->DriverUnload = ItokUnload;

    /* legacy device name: the game CreateFile("\\\\.\\ITOKEN2") for the
       SmartCardReader channel (0x47); create it in addition to the {171638F7}
       PnP interface. All ioctls complete success (replay in user mode). */
    RtlInitUnicodeString(&devName, L"\\Device\\ITOKEN2");
    RtlInitUnicodeString(&linkName, L"\\DosDevices\\ITOKEN2");
    status = IoCreateDevice(DriverObject, 0, &devName, FILE_DEVICE_UNKNOWN,
                            FILE_DEVICE_SECURE_OPEN, FALSE, &g_LegacyDev);
    if (NT_SUCCESS(status)) {
        g_LegacyDev->Flags &= ~DO_DEVICE_INITIALIZING;
        IoCreateSymbolicLink(&linkName, &devName);
    }

    return STATUS_SUCCESS;
}
