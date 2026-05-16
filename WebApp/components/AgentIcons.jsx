// Inline SVG icons used across agent UI. Keeping these as simple stroked
// glyphs avoids pulling in an icon library and keeps colors theme-driven.

const baseProps = {
  width: 18,
  height: 18,
  viewBox: "0 0 24 24",
  fill: "none",
  stroke: "currentColor",
  strokeWidth: 1.8,
  strokeLinecap: "round",
  strokeLinejoin: "round",
  "aria-hidden": true,
};

export function BrainIcon(props) {
  return (
    <svg {...baseProps} {...props}>
      <path d="M9 4a3 3 0 0 0-3 3v.5A2.5 2.5 0 0 0 4 10v.5A2.5 2.5 0 0 0 6 13v.5A2.5 2.5 0 0 0 9 16v2a2 2 0 0 0 4 0V6a2 2 0 0 0-4 0Z" />
      <path d="M15 4a3 3 0 0 1 3 3v.5A2.5 2.5 0 0 1 20 10v.5A2.5 2.5 0 0 1 18 13v.5A2.5 2.5 0 0 1 15 16" />
    </svg>
  );
}

export function MemoryIcon(props) {
  return (
    <svg {...baseProps} {...props}>
      <rect x="4" y="4" width="16" height="16" rx="2" />
      <path d="M8 4v4M12 4v4M16 4v4M8 16v4M12 16v4M16 16v4" />
      <rect x="8" y="8" width="8" height="8" rx="1" />
    </svg>
  );
}

export function WeatherIcon(props) {
  return (
    <svg {...baseProps} {...props}>
      <path d="M7 18a4 4 0 1 1 1.5-7.7A6 6 0 0 1 20 12a4 4 0 0 1-1 7.9" />
    </svg>
  );
}

export function CompetitorIcon(props) {
  return (
    <svg {...baseProps} {...props}>
      <path d="M3 20h18" />
      <rect x="5" y="11" width="3" height="9" rx="0.5" />
      <rect x="10.5" y="7" width="3" height="13" rx="0.5" />
      <rect x="16" y="14" width="3" height="6" rx="0.5" />
    </svg>
  );
}

export function EventIcon(props) {
  return (
    <svg {...baseProps} {...props}>
      <rect x="4" y="5" width="16" height="15" rx="2" />
      <path d="M4 9h16M9 3v4M15 3v4" />
      <circle cx="12" cy="14" r="1.5" />
    </svg>
  );
}

export function HistoryIcon(props) {
  return (
    <svg {...baseProps} {...props}>
      <path d="M3 12a9 9 0 1 0 3-6.7" />
      <path d="M3 4v5h5" />
      <path d="M12 8v5l3 2" />
    </svg>
  );
}

export function CalcIcon(props) {
  return (
    <svg {...baseProps} {...props}>
      <rect x="5" y="3" width="14" height="18" rx="2" />
      <path d="M8 7h8M8 11h2M12 11h2M16 11h0M8 15h2M12 15h2M16 15h0M8 19h2M12 19h2M16 19h0" />
    </svg>
  );
}

export function ShieldIcon(props) {
  return (
    <svg {...baseProps} {...props}>
      <path d="M12 3 5 6v6c0 4 3 7 7 9 4-2 7-5 7-9V6Z" />
      <path d="m9 12 2 2 4-4" />
    </svg>
  );
}

export function SendIcon(props) {
  return (
    <svg {...baseProps} {...props}>
      <path d="M4 12 21 4l-3 17-7-6-7-3Z" />
    </svg>
  );
}

export function SaveIcon(props) {
  return (
    <svg {...baseProps} {...props}>
      <path d="M5 4h11l3 3v13H5z" />
      <path d="M8 4v5h7V4M8 14h8v6H8z" />
    </svg>
  );
}

export function PyToolIcon(props) {
  return (
    <svg {...baseProps} {...props}>
      <path d="M6 3h8l4 4v14H6z" />
      <path d="M14 3v5h5" />
      <path d="m8 13 2-2-2-2" />
      <path d="M11 16h5" />
    </svg>
  );
}

export function SkillIcon(props) {
  return (
    <svg {...baseProps} {...props}>
      <path d="M12 3 5 7v10l7 4 7-4V7z" />
      <path d="M12 8v8M8.5 10l3.5-2 3.5 2M8.5 14l3.5 2 3.5-2" />
    </svg>
  );
}

export function ParallelGroupIcon(props) {
  return (
    <svg {...baseProps} {...props}>
      <circle cx="6" cy="7" r="2" />
      <circle cx="18" cy="7" r="2" />
      <circle cx="12" cy="17" r="2" />
      <path d="M8 7h2a2 2 0 0 1 2 2v6" />
      <path d="M16 7h-2a2 2 0 0 0-2 2" />
    </svg>
  );
}

export function CheckIcon(props) {
  return (
    <svg {...baseProps} {...props}>
      <path d="m5 12 5 5L20 7" />
    </svg>
  );
}

export function PlusIcon(props) {
  return (
    <svg {...baseProps} {...props}>
      <path d="M12 5v14M5 12h14" />
    </svg>
  );
}

export function PlayIcon(props) {
  return (
    <svg {...baseProps} {...props}>
      <path d="M7 5v14l12-7Z" />
    </svg>
  );
}

export function StopIcon(props) {
  return (
    <svg {...baseProps} {...props}>
      <path d="M8 3h8l5 5v8l-5 5H8l-5-5V8Z" />
      <rect x="8.5" y="8.5" width="7" height="7" rx="1" fill="currentColor" stroke="none" />
    </svg>
  );
}

export function ArrowRightIcon(props) {
  return (
    <svg {...baseProps} {...props}>
      <path d="M5 12h14M13 6l6 6-6 6" />
    </svg>
  );
}

export function SparkleIcon(props) {
  return (
    <svg {...baseProps} {...props}>
      <path d="M12 3v4M12 17v4M3 12h4M17 12h4M6 6l3 3M15 15l3 3M6 18l3-3M15 9l3-3" />
    </svg>
  );
}

export function UserIcon(props) {
  return (
    <svg {...baseProps} {...props}>
      <circle cx="12" cy="8" r="3.5" />
      <path d="M5 20a7 7 0 0 1 14 0" />
    </svg>
  );
}

export function ChatIcon(props) {
  return (
    <svg {...baseProps} {...props}>
      <path d="M5 6.5A3.5 3.5 0 0 1 8.5 3h7A3.5 3.5 0 0 1 19 6.5v5A3.5 3.5 0 0 1 15.5 15H11l-5 4v-4.4A3.5 3.5 0 0 1 3 11.2V6.5Z" />
      <path d="M8 8h8M8 11h5" />
    </svg>
  );
}

export function OccupancyIcon(props) {
  return (
    <svg {...baseProps} {...props}>
      <path d="M3 21V11l9-7 9 7v10z" />
      <path d="M9 21v-6h6v6" />
    </svg>
  );
}

const ICONS = {
  brain: BrainIcon,
  memory: MemoryIcon,
  weather: WeatherIcon,
  competitor: CompetitorIcon,
  event: EventIcon,
  history: HistoryIcon,
  calc: CalcIcon,
  shield: ShieldIcon,
  send: SendIcon,
  save: SaveIcon,
  pyTool: PyToolIcon,
  skill: SkillIcon,
  parallelGroup: ParallelGroupIcon,
  check: CheckIcon,
  plus: PlusIcon,
  play: PlayIcon,
  stop: StopIcon,
  arrow: ArrowRightIcon,
  sparkle: SparkleIcon,
  user: UserIcon,
  chat: ChatIcon,
  occupancy: OccupancyIcon,
};

export function StepIcon({ name, ...rest }) {
  const Component = ICONS[name] || SparkleIcon;
  return <Component {...rest} />;
}

export default StepIcon;
