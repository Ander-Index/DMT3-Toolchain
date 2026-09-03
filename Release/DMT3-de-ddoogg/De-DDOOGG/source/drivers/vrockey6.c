/*
 * vrockey6.c - virtual Feitian Rockey6 SMART PLUS HID dongle (VID_096E PID_0405).
 *
 * Pure WDM lower-filter HID minidriver (MsHidKmdf architecture, like vhidmini2):
 *   - INF installs hidclass as function driver via MsHidKmdf.inf
 *   - this driver is the lower filter that answers internal IOCTL_HID_* requests
 *   - presents: UsagePage FFA0 / Usage A2, 65-byte in/out/feature reports,
 *     product "USB Dongle 32", manufacturer "FS", VID 096E PID 0405 ver 0100
 *   - IOCTL_HID_READ/WRITE_REPORT: replay engine (transcript table vR_Transcript)
 */

#include <ntddk.h>

// ---------------------------------------------------------------------------
// self-contained HID definitions (WDK install lacks hidclass.h)
// ---------------------------------------------------------------------------
#ifndef FILE_DEVICE_HID
#define FILE_DEVICE_HID 0x0000000B
#endif

#define HID_CTL_CODE(n) CTL_CODE(FILE_DEVICE_HID, (n), METHOD_NEITHER, FILE_ANY_ACCESS)

#define IOCTL_HID_GET_DEVICE_DESCRIPTOR          HID_CTL_CODE(0)
#define IOCTL_HID_GET_REPORT_DESCRIPTOR          HID_CTL_CODE(1)
#define IOCTL_HID_READ_REPORT                    HID_CTL_CODE(2)
#define IOCTL_HID_WRITE_REPORT                   HID_CTL_CODE(3)
#define IOCTL_HID_GET_STRING                     HID_CTL_CODE(4)
#define IOCTL_HID_ACTIVATE_DEVICE                HID_CTL_CODE(7)
#define IOCTL_HID_DEACTIVATE_DEVICE              HID_CTL_CODE(8)
#define IOCTL_HID_GET_DEVICE_ATTRIBUTES          HID_CTL_CODE(9)
#define IOCTL_HID_SEND_IDLE_NOTIFICATION_REQUEST HID_CTL_CODE(10)
#define IOCTL_HID_GET_FEATURE                    HID_CTL_CODE(9)   /* placeholder, fixed below */
#define IOCTL_HID_SET_FEATURE                    HID_CTL_CODE(10)  /* placeholder, fixed below */

// real feature ioctls are METHOD_OUT/IN_DIRECT CTL_CODEs
#undef IOCTL_HID_GET_FEATURE
#undef IOCTL_HID_SET_FEATURE
#define IOCTL_HID_GET_FEATURE   CTL_CODE(FILE_DEVICE_HID, 100, METHOD_OUT_DIRECT, FILE_ANY_ACCESS)
#define IOCTL_HID_SET_FEATURE   CTL_CODE(FILE_DEVICE_HID, 101, METHOD_IN_DIRECT,  FILE_ANY_ACCESS)
#define IOCTL_HID_GET_INPUT_REPORT CTL_CODE(FILE_DEVICE_HID, 102, METHOD_OUT_DIRECT, FILE_ANY_ACCESS)
#define IOCTL_HID_SET_OUTPUT_REPORT CTL_CODE(FILE_DEVICE_HID, 103, METHOD_IN_DIRECT, FILE_ANY_ACCESS)

#define HID_HID_DESCRIPTOR_TYPE     0x21
#define HID_REPORT_DESCRIPTOR_TYPE  0x22
#define HID_STRING_ID_IMANUFACTURER 14
#define HID_STRING_ID_IPRODUCT      15
#define HID_STRING_ID_ISERIALNUMBER 16

#include <pshpack1.h>
typedef struct _HID_DESC {
    UCHAR   bLength;
    UCHAR   bDescriptorType;
    USHORT  bcdHID;
    UCHAR   bCountry;
    UCHAR   bNumDescriptors;
    struct {
        UCHAR   bReportType;
        USHORT  wReportLength;
    } DescriptorList[1];
} HID_DESC, *PHID_DESC;
#include <poppack.h>

typedef struct _HID_DEV_ATTR {
    ULONG Size;
    USHORT VendorID;
    USHORT ProductID;
    USHORT VersionNumber;
    USHORT Reserved[11];
} HID_DEV_ATTR, *PHID_DEV_ATTR;

typedef struct _HID_XFER_PACKET_LOCAL {
    PUCHAR reportBuffer;
    ULONG  reportBufferLen;
    UCHAR  reportId;
} HID_XFER_PACKET_LOCAL, *PHID_XFER_PACKET_LOCAL;

#define DOG_VID      0x096E
#define DOG_PID      0x0405
#define DOG_VERSION  0x0100
#define REPORT_LEN   65
/* MsHidKmdf implicitly adds a report-ID byte in caps (65->66). Declare
   report count 64 so caps come out as 65 and 65-byte no-ID transfers pass.
   Protocol byte0 is always 0x00, which doubles as the implicit report ID. */
#define REPORT_DESC_COUNT  64

// ---------------------------------------------------------------------------
// report descriptor: usage page FFA0, usage A2, 65-byte in/out/feature reports
// ---------------------------------------------------------------------------
static const UCHAR ReportDescriptor[] = {
    0x06, 0xA0, 0xFF,       // Usage Page (Generic Desktop: FFA0 vendor)
    0x09, 0xA2,             // Usage (A2)
    0xA1, 0x01,             // Collection (Application)
    0x09, 0xA2,             //   Usage (A2)
    0x15, 0x00,             //   Logical Minimum (0)
    0x26, 0xFF, 0x00,       //   Logical Maximum (255)
    0x75, 0x08,             //   Report Size (8)
    0x95, REPORT_DESC_COUNT,       //   Report Count (65)
    0x81, 0x00,             //   Input (Data,Var,Abs)
    0x09, 0xA2,             //   Usage (A2)
    0x15, 0x00,             //   Logical Minimum (0)
    0x26, 0xFF, 0x00,       //   Logical Maximum (255)
    0x75, 0x08,             //   Report Size (8)
    0x95, REPORT_DESC_COUNT,       //   Report Count (65)
    0x91, 0x00,             //   Output (Data,Var,Abs)
    0x09, 0xA2,             //   Usage (A2)
    0x15, 0x00,             //   Logical Minimum (0)
    0x26, 0xFF, 0x00,       //   Logical Maximum (255)
    0x75, 0x08,             //   Report Size (8)
    0x95, REPORT_DESC_COUNT,       //   Report Count (65)
    0xB1, 0x00,             //   Feature (Data,Var,Abs)
    0xC0                    // End Collection
};

static const HID_DESC HidDescriptor = {
    0x09,                   // bLength
    HID_HID_DESCRIPTOR_TYPE,// 0x21
    0x0100,                 // bcdHID
    0x00,                   // bCountry
    0x01,                   // bNumDescriptors
    {
        HID_REPORT_DESCRIPTOR_TYPE,   // 0x22
        sizeof(ReportDescriptor)
    }
};

static const WCHAR ProductString[] = L"USB Dongle 32";
static const WCHAR ManufacturerString[] = L"FS";

// ---------------------------------------------------------------------------
// transcript state machine (vrockey6_transcript.h provides the data):
//   write cmd3 -> next 3 reads serve the 136-byte blob (3x65B reports)
//   write cmd1 -> next read serves the ATR ("DEFAULT ATR" id string)
//   write cmd2 -> next read serves VChalPairs[challenge].Resp (8-byte challenge
//                 at write offset 12; unknown challenge -> zeros)
// ---------------------------------------------------------------------------
#include "vrockey6_transcript.h"   // VT_Blob[], VT_Atr, VChalPairs[], VChalPairsCount

// ---------------------------------------------------------------------------
typedef struct _DEVICE_EXT {
    PDEVICE_OBJECT Self;
    PDEVICE_OBJECT NextLower;
    ULONG          ReadState;      // VR_IDLE / VR_BLOB n / VR_ATR / VR_CHAL
    ULONG          BlobPart;
    const UCHAR   *ChalResp;       // selected response for VR_CHAL
    UCHAR          LastWrite[REPORT_LEN];
    KSPIN_LOCK     Lock;
} DEVICE_EXT, *PDEVICE_EXT;

#define VR_IDLE  0
#define VR_BLOB  1
#define VR_ATR   2
#define VR_CHAL  3

#define POOL_TAG 'k6rV'

// ---------------------------------------------------------------------------
static NTSTATUS
CopyToUserBuffer(PIRP Irp, const VOID *Src, ULONG Len)
{
    PVOID dst = Irp->UserBuffer;
    if (!dst)
        return STATUS_INVALID_PARAMETER;
    // hidclass supplies kernel-valid buffers for these internal IOCTLs
    __try {
        RtlCopyMemory(dst, Src, Len);
    } __except (EXCEPTION_EXECUTE_HANDLER) {
        return STATUS_ACCESS_VIOLATION;
    }
    Irp->IoStatus.Information = Len;
    return STATUS_SUCCESS;
}

static NTSTATUS
HandleGetString(PIRP Irp, PIO_STACK_LOCATION sp)
{
    ULONG stringId = PtrToUlong(sp->Parameters.DeviceIoControl.Type3InputBuffer) & 0xFFFF; /* high word = LANGID */
    NTSTATUS st;
    switch (stringId) {
    case HID_STRING_ID_IPRODUCT:   /* 15 */
        st = CopyToUserBuffer(Irp, ProductString, sizeof(ProductString));
        break;
    case HID_STRING_ID_IMANUFACTURER:  /* 14 */
        st = CopyToUserBuffer(Irp, ManufacturerString, sizeof(ManufacturerString));
        break;
    case HID_STRING_ID_ISERIALNUMBER:  /* 16 */
    default:
        Irp->IoStatus.Information = 0;
        st = STATUS_INVALID_PARAMETER;   // real dongle has no serial string
        break;
    }
    return st;
}

static PHID_XFER_PACKET_LOCAL
GetHidXferPacket(PIRP Irp)
{
    if (Irp->UserBuffer)
        return (PHID_XFER_PACKET_LOCAL)Irp->UserBuffer;
    return NULL;
}

// advance protocol on write; produce response for read
static NTSTATUS
HandleWriteReport(PDEVICE_EXT ext, PIRP Irp)
{
    KIRQL oldIrql;
    PHID_XFER_PACKET_LOCAL p = GetHidXferPacket(Irp);
    ULONG cmd;
    if (!p || !p->reportBuffer || p->reportBufferLen < 1) {
        Irp->IoStatus.Information = 0;
        return STATUS_INVALID_PARAMETER;
    }
    KeAcquireSpinLock(&ext->Lock, &oldIrql);
    RtlZeroMemory(ext->LastWrite, REPORT_LEN);
    RtlCopyMemory(ext->LastWrite, p->reportBuffer,
                  p->reportBufferLen < REPORT_LEN ? p->reportBufferLen : REPORT_LEN);
    cmd = *(USHORT *)(ext->LastWrite + 10);   // 'R6' sub-command id @ offset 10
    switch (cmd) {
    case 0x0003:
        ext->ReadState = VR_BLOB;
        ext->BlobPart = 0;
        break;
    case 0x0001:
        ext->ReadState = VR_ATR;
        break;
    case 0x0002: {
        /* 8-byte challenge at offset 13 (offset 12 = challenge length 08) */
        ULONG i;
        ext->ChalResp = NULL;
        for (i = 0; i < VChalPairsCount; i++) {
            if (RtlEqualMemory(ext->LastWrite + 13, VChalPairs[i].Key, 8)) {
                ext->ChalResp = VChalPairs[i].Resp;
                break;
            }
        }
        ext->ReadState = VR_CHAL;
        break;
    }
    default:
        ext->ReadState = VR_IDLE;
        break;
    }
    KeReleaseSpinLock(&ext->Lock, oldIrql);
    Irp->IoStatus.Information = 0;
    return STATUS_SUCCESS;
}

static NTSTATUS
HandleReadReport(PDEVICE_EXT ext, PIRP Irp)
{
    KIRQL oldIrql;
    const UCHAR *resp = NULL;
    PHID_XFER_PACKET_LOCAL p = GetHidXferPacket(Irp);
    ULONG fill;
    if (!p || !p->reportBuffer || p->reportBufferLen < 1) {
        Irp->IoStatus.Information = 0;
        return STATUS_INVALID_PARAMETER;
    }
    fill = p->reportBufferLen < REPORT_LEN ? p->reportBufferLen : REPORT_LEN;
    KeAcquireSpinLock(&ext->Lock, &oldIrql);
    switch (ext->ReadState) {
    case VR_BLOB:
        resp = VT_Blob[ext->BlobPart];
        if (ext->BlobPart < 2)
            ext->BlobPart++;
        else
            ext->ReadState = VR_IDLE;
        break;
    case VR_ATR:
        resp = VT_Atr;
        ext->ReadState = VR_IDLE;
        break;
    case VR_CHAL:
        resp = ext->ChalResp;   // NULL if unknown challenge -> zeros
        ext->ReadState = VR_IDLE;
        break;
    default:
        break;
    }
    KeReleaseSpinLock(&ext->Lock, oldIrql);
    if (resp) {
        RtlCopyMemory(p->reportBuffer, resp, fill);
        if (fill < p->reportBufferLen)
            RtlZeroMemory(p->reportBuffer + fill, p->reportBufferLen - fill);
    } else {
        RtlZeroMemory(p->reportBuffer, p->reportBufferLen);
    }
    p->reportId = 0;
    Irp->IoStatus.Information = 0;
    return STATUS_SUCCESS;
}

static NTSTATUS
HandleGetFeature(PDEVICE_EXT ext, PIRP Irp)
{
    PHID_XFER_PACKET_LOCAL p = GetHidXferPacket(Irp);
    if (!p || !p->reportBuffer || p->reportBufferLen < REPORT_LEN) {
        Irp->IoStatus.Information = 0;
        return STATUS_INVALID_PARAMETER;
    }
    RtlZeroMemory(p->reportBuffer, REPORT_LEN);
    p->reportId = 0;
    Irp->IoStatus.Information = 0;
    return STATUS_SUCCESS;
}

// ---------------------------------------------------------------------------
static NTSTATUS
VrInternalDeviceControl(PDEVICE_OBJECT DeviceObject, PIRP Irp)
{
    PDEVICE_EXT ext = (PDEVICE_EXT)DeviceObject->DeviceExtension;
    PIO_STACK_LOCATION sp = IoGetCurrentIrpStackLocation(Irp);
    ULONG code = sp->Parameters.DeviceIoControl.IoControlCode;
    NTSTATUS status;

    switch (code) {
    case IOCTL_HID_GET_DEVICE_DESCRIPTOR:
        status = CopyToUserBuffer(Irp, &HidDescriptor, HidDescriptor.bLength);
        break;

    case IOCTL_HID_GET_REPORT_DESCRIPTOR:
        status = CopyToUserBuffer(Irp, ReportDescriptor, sizeof(ReportDescriptor));
        break;

    case IOCTL_HID_GET_DEVICE_ATTRIBUTES: {
        HID_DEV_ATTR attr;
        attr.Size = sizeof(attr);
        attr.VendorID = DOG_VID;
        attr.ProductID = DOG_PID;
        attr.VersionNumber = DOG_VERSION;
        RtlZeroMemory(attr.Reserved, sizeof(attr.Reserved));
        status = CopyToUserBuffer(Irp, &attr, sizeof(attr));
        break;
    }

    case IOCTL_HID_GET_STRING:
        status = HandleGetString(Irp, sp);
        break;

    case IOCTL_HID_WRITE_REPORT:
        status = HandleWriteReport(ext, Irp);
        break;

    case IOCTL_HID_READ_REPORT:
        status = HandleReadReport(ext, Irp);
        break;

    case IOCTL_HID_GET_FEATURE:
        status = HandleGetFeature(ext, Irp);
        break;

    case IOCTL_HID_SET_FEATURE:
    case IOCTL_HID_SET_OUTPUT_REPORT:
    case IOCTL_HID_GET_INPUT_REPORT:
    case IOCTL_HID_ACTIVATE_DEVICE:
    case IOCTL_HID_DEACTIVATE_DEVICE:
        Irp->IoStatus.Information = 0;
        status = STATUS_SUCCESS;
        break;

    default:
        Irp->IoStatus.Information = 0;
        status = STATUS_NOT_IMPLEMENTED;
        break;
    }

    Irp->IoStatus.Status = status;
    IoCompleteRequest(Irp, IO_NO_INCREMENT);
    return status;
}

// ---------------------------------------------------------------------------
static NTSTATUS
VrPnp(PDEVICE_OBJECT DeviceObject, PIRP Irp)
{
    PDEVICE_EXT ext = (PDEVICE_EXT)DeviceObject->DeviceExtension;
    PIO_STACK_LOCATION sp = IoGetCurrentIrpStackLocation(Irp);
    NTSTATUS status;

    switch (sp->MinorFunction) {
    case IRP_MN_REMOVE_DEVICE:
        IoSkipCurrentIrpStackLocation(Irp);
        status = IoCallDriver(ext->NextLower, Irp);
        IoDetachDevice(ext->NextLower);
        IoDeleteDevice(DeviceObject);
        return status;

    case IRP_MN_START_DEVICE:
        IoSkipCurrentIrpStackLocation(Irp);
        status = IoCallDriver(ext->NextLower, Irp);
        if (NT_SUCCESS(status)) {
            ext->ReadState = VR_IDLE; ext->BlobPart = 0;
        }
        return status;

    default:
        IoSkipCurrentIrpStackLocation(Irp);
        return IoCallDriver(ext->NextLower, Irp);
    }
}

static NTSTATUS
VrPassDown(PDEVICE_OBJECT DeviceObject, PIRP Irp)
{
    PDEVICE_EXT ext = (PDEVICE_EXT)DeviceObject->DeviceExtension;
    IoSkipCurrentIrpStackLocation(Irp);
    return IoCallDriver(ext->NextLower, Irp);
}

static NTSTATUS
VrAddDevice(PDRIVER_OBJECT DriverObject, PDEVICE_OBJECT PhysicalDeviceObject)
{
    NTSTATUS status;
    PDEVICE_OBJECT fdo;
    PDEVICE_EXT ext;

    UNREFERENCED_PARAMETER(DriverObject);

    status = IoCreateDevice(DriverObject,
                            sizeof(DEVICE_EXT),
                            NULL,
                            FILE_DEVICE_UNKNOWN,
                            FILE_DEVICE_SECURE_OPEN,
                            FALSE,
                            &fdo);
    if (!NT_SUCCESS(status))
        return status;

    ext = (PDEVICE_EXT)fdo->DeviceExtension;
    RtlZeroMemory(ext, sizeof(DEVICE_EXT));
    ext->Self = fdo;
    ext->ReadState = VR_IDLE; ext->BlobPart = 0;
    KeInitializeSpinLock(&ext->Lock);

    ext->NextLower = IoAttachDeviceToDeviceStack(fdo, PhysicalDeviceObject);
    if (!ext->NextLower) {
        IoDeleteDevice(fdo);
        return STATUS_DEVICE_NOT_CONNECTED;
    }

    fdo->Flags |= DO_POWER_PAGABLE;
    fdo->Flags &= ~DO_DEVICE_INITIALIZING;

    return STATUS_SUCCESS;
}

static VOID
VrUnload(PDRIVER_OBJECT DriverObject)
{
    UNREFERENCED_PARAMETER(DriverObject);
}

NTSTATUS
DriverEntry(PDRIVER_OBJECT DriverObject, PUNICODE_STRING RegistryPath)
{
    ULONG i;
    UNREFERENCED_PARAMETER(RegistryPath);

    for (i = 0; i <= IRP_MJ_MAXIMUM_FUNCTION; i++)
        DriverObject->MajorFunction[i] = VrPassDown;

    DriverObject->MajorFunction[IRP_MJ_INTERNAL_DEVICE_CONTROL] = VrInternalDeviceControl;
    DriverObject->MajorFunction[IRP_MJ_PNP] = VrPnp;
    DriverObject->DriverExtension->AddDevice = VrAddDevice;
    DriverObject->DriverUnload = VrUnload;

    return STATUS_SUCCESS;
}
