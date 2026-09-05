# Read-only SCM configuration API. Native console text is not a data contract.
function Get-IzoServiceRecoveryDelays {
    param([string]$ServiceName = 'IZOBackend')

    if (-not ('Izo.Recovery.ServiceConfiguration' -as [type])) {
        Add-Type -TypeDefinition @'
using System;
using System.ComponentModel;
using System.Runtime.InteropServices;

namespace Izo.Recovery {
    public static class ServiceConfiguration {
        [StructLayout(LayoutKind.Sequential)]
        private struct FailureActions {
            public uint ResetPeriod;
            public IntPtr RebootMessage;
            public IntPtr Command;
            public uint ActionCount;
            public IntPtr Actions;
        }
        [DllImport("advapi32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
        private static extern IntPtr OpenSCManager(string machine, string database, uint access);
        [DllImport("advapi32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
        private static extern IntPtr OpenService(IntPtr manager, string name, uint access);
        [DllImport("advapi32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
        private static extern bool QueryServiceConfig2(IntPtr service, uint level, IntPtr buffer, uint size, out uint needed);
        [DllImport("advapi32.dll", SetLastError = true)]
        private static extern bool CloseServiceHandle(IntPtr handle);

        public static uint[] ReadDelays(string name) {
            IntPtr manager = IntPtr.Zero, service = IntPtr.Zero, buffer = IntPtr.Zero;
            try {
                manager = OpenSCManager(null, null, 1); // SC_MANAGER_CONNECT
                if (manager == IntPtr.Zero) throw new Win32Exception(Marshal.GetLastWin32Error());
                service = OpenService(manager, name, 1); // SERVICE_QUERY_CONFIG only
                if (service == IntPtr.Zero) throw new Win32Exception(Marshal.GetLastWin32Error());
                uint needed;
                bool queried = QueryServiceConfig2(service, 2, IntPtr.Zero, 0, out needed);
                int error = Marshal.GetLastWin32Error();
                if (!queried && error != 122) throw new Win32Exception(error);
                if (needed < Marshal.SizeOf(typeof(FailureActions)) || needed > 1048576)
                    throw new InvalidOperationException("Unexpected SCM configuration size.");
                buffer = Marshal.AllocHGlobal(checked((int)needed));
                if (!QueryServiceConfig2(service, 2, buffer, needed, out needed))
                    throw new Win32Exception(Marshal.GetLastWin32Error());
                var config = (FailureActions)Marshal.PtrToStructure(buffer, typeof(FailureActions));
                if (config.ActionCount > 128 || (config.ActionCount != 0 && config.Actions == IntPtr.Zero))
                    throw new InvalidOperationException("Unexpected SCM failure action array.");
                var delays = new uint[config.ActionCount];
                for (int i = 0; i < delays.Length; i++)
                    delays[i] = unchecked((uint)Marshal.ReadInt32(config.Actions, checked(i * 8 + 4)));
                return delays;
            } finally {
                if (buffer != IntPtr.Zero) Marshal.FreeHGlobal(buffer);
                if (service != IntPtr.Zero) CloseServiceHandle(service);
                if (manager != IntPtr.Zero) CloseServiceHandle(manager);
            }
        }
    }
}
'@ -ErrorAction Stop
    }
    [Izo.Recovery.ServiceConfiguration]::ReadDelays($ServiceName)
}
