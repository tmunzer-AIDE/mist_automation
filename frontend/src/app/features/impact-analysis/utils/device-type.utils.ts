export function deviceTypeIcon(type: string): string {
  switch (type) {
    case 'ap':
      return 'wifi';
    case 'switch':
      return 'device_hub';
    case 'gateway':
      return 'router';
    default:
      return 'devices';
  }
}

export function formatDeviceType(type: string): string {
  switch (type) {
    case 'ap':
      return 'Access Point';
    case 'switch':
      return 'Switch';
    case 'gateway':
      return 'Gateway';
    default:
      return type;
  }
}
