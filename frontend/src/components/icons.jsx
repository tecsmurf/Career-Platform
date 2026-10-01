// Lightweight inline icon set (stroke, currentColor). No external icon lib.
const base = {
  fill: 'none',
  stroke: 'currentColor',
  strokeWidth: 2,
  strokeLinecap: 'round',
  strokeLinejoin: 'round',
  viewBox: '0 0 24 24',
  width: 18,
  height: 18,
  'aria-hidden': true,
};

export const Logo = (p) => (
  <svg {...base} strokeWidth="2.2" {...p}><path d="M4 7h16M4 12h16M4 17h10" /></svg>
);
export const Briefcase = (p) => (
  <svg {...base} {...p}><rect x="3" y="7" width="18" height="13" rx="2" /><path d="M8 7V5a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2M3 12h18" /></svg>
);
export const Search = (p) => (
  <svg {...base} {...p}><circle cx="11" cy="11" r="7" /><path d="m21 21-4.3-4.3" /></svg>
);
export const Plus = (p) => (<svg {...base} {...p}><path d="M12 5v14M5 12h14" /></svg>);
export const Edit = (p) => (<svg {...base} {...p}><path d="M12 20h9" /><path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4Z" /></svg>);
export const Trash = (p) => (<svg {...base} {...p}><path d="M3 6h18M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2M6 6l1 14a2 2 0 0 0 2 2h6a2 2 0 0 0 2-2l1-14" /></svg>);
export const MapPin = (p) => (<svg {...base} {...p}><path d="M20 10c0 6-8 12-8 12s-8-6-8-12a8 8 0 0 1 16 0Z" /><circle cx="12" cy="10" r="3" /></svg>);
export const Money = (p) => (<svg {...base} {...p}><line x1="12" y1="2" x2="12" y2="22" /><path d="M17 6.5c0-1.9-2.2-3-5-3s-5 1.1-5 3 2.2 3 5 3 5 1.1 5 3-2.2 3-5 3-5-1.1-5-3" /></svg>);
export const Calendar = (p) => (<svg {...base} {...p}><rect x="3" y="4" width="18" height="18" rx="2" /><path d="M16 2v4M8 2v4M3 10h18" /></svg>);
export const LinkIcon = (p) => (<svg {...base} {...p}><path d="M10 13a5 5 0 0 0 7 0l2-2a5 5 0 0 0-7-7l-1 1" /><path d="M14 11a5 5 0 0 0-7 0l-2 2a5 5 0 0 0 7 7l1-1" /></svg>);
export const Mail = (p) => (<svg {...base} {...p}><rect x="3" y="5" width="18" height="14" rx="2" /><path d="m3 7 9 6 9-6" /></svg>);
export const Close = (p) => (<svg {...base} {...p}><path d="M18 6 6 18M6 6l12 12" /></svg>);
export const Eye = (p) => (<svg {...base} {...p}><path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7-10-7-10-7Z" /><circle cx="12" cy="12" r="3" /></svg>);
export const EyeOff = (p) => (<svg {...base} {...p}><path d="M9.9 4.2A9.5 9.5 0 0 1 12 4c6.5 0 10 7 10 7a15 15 0 0 1-3 3.6M6.6 6.6A15.6 15.6 0 0 0 2 11s3.5 7 10 7a9.3 9.3 0 0 0 4-.9" /><path d="M9.9 9.9a3 3 0 0 0 4.2 4.2M3 3l18 18" /></svg>);
export const Check = (p) => (<svg {...base} {...p}><path d="M20 6 9 17l-5-5" /></svg>);
export const CheckCircle = (p) => (<svg {...base} {...p}><path d="M22 11.1V12a10 10 0 1 1-5.9-9.1" /><path d="M22 4 12 14.1l-3-3" /></svg>);
export const AlertCircle = (p) => (<svg {...base} {...p}><circle cx="12" cy="12" r="10" /><path d="M12 8v5M12 16.5v.01" /></svg>);
export const AlertTriangle = (p) => (<svg {...base} {...p}><path d="M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0Z" /><path d="M12 9v4M12 17h.01" /></svg>);
export const ChevronLeft = (p) => (<svg {...base} {...p}><path d="m15 18-6-6 6-6" /></svg>);
export const ChevronRight = (p) => (<svg {...base} {...p}><path d="m9 18 6-6-6-6" /></svg>);
export const Logout = (p) => (<svg {...base} {...p}><path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4" /><path d="m16 17 5-5-5-5M21 12H9" /></svg>);
export const Inbox = (p) => (<svg {...base} {...p}><path d="M22 12h-6l-2 3h-4l-2-3H2" /><path d="M5.5 5.5 2 12v6a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2v-6l-3.5-6.5A2 2 0 0 0 16.8 4H7.2a2 2 0 0 0-1.7 1.5Z" /></svg>);
export const Sparkle = (p) => (<svg {...base} {...p}><path d="M12 3l1.9 5.6L19.5 10l-5.6 1.4L12 17l-1.9-5.6L4.5 10l5.6-1.4Z" /></svg>);
export const Shield = (p) => (<svg {...base} {...p}><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10Z" /><path d="m9 12 2 2 4-4" /></svg>);
export const BarChart = (p) => (<svg {...base} {...p}><path d="M3 3v18h18" /><rect x="7" y="11" width="3" height="6" /><rect x="12" y="7" width="3" height="10" /><rect x="17" y="13" width="3" height="4" /></svg>);
export const Refresh = (p) => (<svg {...base} {...p}><path d="M21 12a9 9 0 0 1-15.5 6.2L3 16" /><path d="M3 21v-5h5" /><path d="M3 12a9 9 0 0 1 15.5-6.2L21 8" /><path d="M21 3v5h-5" /></svg>);
export const Unlink = (p) => (<svg {...base} {...p}><path d="m18.8 13.4 1.7-1.7a5 5 0 0 0-7.2-7.2l-1.7 1.7" /><path d="m5.2 10.6-1.7 1.7a5 5 0 0 0 7.2 7.2l1.7-1.7" /><path d="M8 2v3M2 8h3M16 22v-3M22 16h-3" /></svg>);
export const Clock = (p) => (<svg {...base} {...p}><circle cx="12" cy="12" r="9" /><path d="M12 7v5l3 2" /></svg>);
export const Server = (p) => (<svg {...base} {...p}><rect x="3" y="4" width="18" height="7" rx="2" /><rect x="3" y="13" width="18" height="7" rx="2" /><path d="M7 7.5h.01M7 16.5h.01" /></svg>);
export const Lock = (p) => (<svg {...base} {...p}><rect x="4" y="11" width="16" height="10" rx="2" /><path d="M8 11V7a4 4 0 0 1 8 0v4" /></svg>);
export const ArrowRight = (p) => (<svg {...base} {...p}><path d="M5 12h14M13 6l6 6-6 6" /></svg>);
export const ChevronDown = (p) => (<svg {...base} {...p}><path d="m6 9 6 6 6-6" /></svg>);
export const Activity = (p) => (<svg {...base} {...p}><path d="M22 12h-4l-3 9L9 3l-3 9H2" /></svg>);
