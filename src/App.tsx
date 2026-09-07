import { AnimatePresence, motion } from "framer-motion";
import { useState, type ReactNode } from "react";
import heroImage from "./assets/resolve-workstation.jpg";

type OS = "mac" | "windows";
type Provider = "Antigravity" | "Claude Code" | "Codex" | "Cursor";

// One portable line. Python expands ~ inside Resolve, so the same text is
// correct for every user on macOS, Windows, and Linux. Nothing to substitute.
const consoleCommand =
  'import os;exec(open(os.path.expanduser("~/.resolve-ai-bridge/ResolveConsole.py"),encoding="utf-8").read())';

const installCommands: Record<OS, string> = {
  mac: "python3 install.py",
  windows: "py install.py",
};

const imagePrompt = `Put /Users/me/Desktop/logo.png on video track 2 for 4 seconds
at the playhead, scaled to 40 percent and tucked into the
bottom right corner. Then show me the timeline to confirm it.`;

const editingPrompt = `Take the clip under the playhead. Push it in from 100 to 130
percent over its first two seconds on a preview timeline.
Show me the timeline before and after each step.`;

const remotionCommands = `# Install the official Remotion skill for your coding agents
npx -y skills@latest add remotion-dev/skills -g -y

# Create a clean video project
npx create-video@latest --yes --blank my-video
cd my-video
npm install
npx remotion skills add
npm run dev`;

const configExample = `{
  "mcpServers": {
    "resolve-ai-bridge": {
      "command": "resolve-ai-bridge"
    }
  }
}`;

const providers: Record<Provider, { title: string; steps: string[] }> = {
  Antigravity: {
    title: "Add it to Antigravity",
    steps: [
      "Open the Agent panel, select the three-dot menu, then MCP Servers.",
      "Choose Manage MCP Servers, then View raw config. This opens the config file used by your installed version.",
      "Merge the clean resolve-ai-bridge entry from ~/.resolve-ai-bridge/mcp-config.json into the existing mcpServers object. No env tokens needed.",
      "Save the file, refresh the MCP list, and restart Antigravity if the tools do not appear immediately.",
    ],
  },
  "Claude Code": {
    title: "Add it to Claude Code",
    steps: [
      "Copy the Claude Code command printed by the installer. It is also saved at ~/.resolve-ai-bridge/claude-command.txt.",
      "Run that complete command in a normal terminal. It safely reads the generated JSON with the absolute paths.",
      "Restart Claude Code, run /mcp, and confirm resolve-ai-bridge is connected.",
      "If add-json is unavailable in your version, open its MCP configuration and merge the full mcpServers block instead.",
    ],
  },
  Codex: {
    title: "Add it to Codex",
    steps: [
      "Copy the Codex command printed by the installer. It is also saved at ~/.resolve-ai-bridge/codex-command.txt.",
      "Run that complete codex mcp add command in a normal terminal. It contains the absolute runtime paths without requiring manual tokens.",
      "Run codex mcp list, then restart Codex. The app also supports Settings, MCP servers, Add server, STDIO.",
      "Inside Codex run /mcp, then ask it to call resolve_status before making an edit.",
    ],
  },
  Cursor: {
    title: "Add it to Cursor",
    steps: [
      "Open Cursor Settings, search for MCP, and choose Add new global MCP server.",
      "Merge the resolve-ai-bridge entry from ~/.resolve-ai-bridge/mcp-config.json into mcpServers.",
      "Save the JSON and switch the server on. A green status means Cursor started the local Python server.",
      "Keep Resolve open with a project while you edit.",
    ],
  },
};

const faq = [
  {
    q: "How do I turn the bridge off?",
    a: "Disconnect or disable the resolve-ai-bridge MCP server in your AI client. That removes the tools entirely. If a Console worker is running, also choose Workspace > Scripts > Resolve AI Bridge > Stop AI Bridge, or quit Resolve.",
  },
  {
    q: "Do I still have to replace YOUR_NAME anywhere?",
    a: "No. That was the most common setup failure in version 1.0 and it is gone. The Console line expands ~ inside Resolve's own interpreter, so the same text is correct on every computer, and nothing you paste contains a personal path.",
  },
  {
    q: "Do I have to redo a step every time I open Resolve?",
    a: "In Resolve Free, choose Workspace > Scripts > Resolve AI Bridge > Start AI Bridge once per session. It starts the worker without a Console paste on supported builds. Menu startup is verified on macOS Free 21.0.3.7; other builds retain the Py3 Console fallback.",
  },
  {
    q: "Does this work on free DaVinci Resolve?",
    a: "Yes, the Free workflow uses the connection Resolve supplies to its internal scripts. Review tools use ordinary timeline APIs, not Studio AI features. Individual operations still depend on your Resolve build; source capture excludes timeline effects and needs FFmpeg.",
  },
  {
    q: "Why did my image only last one frame?",
    a: "It was appended as ordinary footage. Use add_image with a duration in seconds instead, then read actual_duration_frames in the reply to see the length Resolve really created.",
  },
  {
    q: "Do I need to copy or configure an authentication token?",
    a: "No. Authentication between the MCP server and DaVinci Resolve is completely automatic via a secure shared local file (~/.resolve-ai-bridge/token.txt). No token needs to be typed or configured in your AI client.",
  },
];

function Icon({ name, className = "h-5 w-5" }: { name: string; className?: string }) {
  const paths: Record<string, ReactNode> = {
    arrow: <path d="M5 12h14m-5-5 5 5-5 5" />,
    check: <path d="m5 12 4 4L19 6" />,
    copy: <><rect x="9" y="9" width="11" height="11" rx="2" /><path d="M15 9V6a2 2 0 0 0-2-2H6a2 2 0 0 0-2 2v7a2 2 0 0 0 2 2h3" /></>,
    nodes: <><circle cx="5" cy="12" r="2" /><circle cx="19" cy="6" r="2" /><circle cx="19" cy="18" r="2" /><path d="m7 12 10-6M7 12l10 6" /></>,
    spark: <><path d="m12 3 1.4 4.6L18 9l-4.6 1.4L12 15l-1.4-4.6L6 9l4.6-1.4L12 3Z" /><path d="m19 15 .7 2.3L22 18l-2.3.7L19 21l-.7-2.3L16 18l2.3-.7L19 15Z" /></>,
    help: <><circle cx="12" cy="12" r="9" /><path d="M9.7 9a2.5 2.5 0 1 1 3.4 2.3c-.8.4-1.1.9-1.1 1.7m0 3h.01" /></>,
  };
  return (
    <svg className={className} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      {paths[name]}
    </svg>
  );
}

function CopyBlock({ code, label, compact = false }: { code: string; label: string; compact?: boolean }) {
  const [copied, setCopied] = useState(false);
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(code);
      setCopied(true);
    } catch {
      const field = document.createElement("textarea");
      field.value = code;
      field.style.position = "fixed";
      field.style.opacity = "0";
      document.body.appendChild(field);
      field.select();
      setCopied(document.execCommand("copy"));
      field.remove();
    }
    window.setTimeout(() => setCopied(false), 1800);
  };
  return (
    <div className="code-shell">
      <div className="flex items-center justify-between gap-4 border-b border-white/10 px-4 py-3 sm:px-5">
        <span className="font-mono text-[11px] uppercase tracking-[0.16em] text-slate-400">{label}</span>
        <button onClick={copy} className="copy-button" aria-label={`Copy ${label}`}>
          <Icon name={copied ? "check" : "copy"} className="h-4 w-4" />
          {copied ? "Copied" : "Copy"}
        </button>
      </div>
      <pre className={`overflow-x-auto px-4 text-slate-100 sm:px-5 ${compact ? "py-4 text-xs" : "py-5 text-[13px]"}`}><code>{code}</code></pre>
    </div>
  );
}

function Reveal({ children, className = "" }: { children: ReactNode; className?: string }) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 26 }}
      whileInView={{ opacity: 1, y: 0 }}
      viewport={{ once: true, amount: 0.16 }}
      transition={{ duration: 0.65, ease: [0.22, 1, 0.36, 1] }}
      className={className}
    >
      {children}
    </motion.div>
  );
}

function SectionIntro({ number, title, text }: { number: string; title: string; text: string }) {
  return (
    <div className="section-grid border-t border-slate-300/80 pt-6">
      <p className="section-number">{number}</p>
      <div className="max-w-3xl">
        <h2 className="font-display text-4xl leading-[1.04] tracking-[-0.035em] text-slate-950 sm:text-5xl lg:text-6xl">{title}</h2>
        <p className="mt-5 max-w-2xl text-base leading-7 text-slate-600 sm:text-lg">{text}</p>
      </div>
    </div>
  );
}

export default function App() {
  const [os, setOS] = useState<OS>("mac");
  const [provider, setProvider] = useState<Provider>("Antigravity");
  const [openFaq, setOpenFaq] = useState(0);

  return (
    <main className="min-h-screen overflow-hidden bg-[#f5f2ea] text-slate-900">
      <section className="relative min-h-[760px] h-[100svh] w-full overflow-hidden bg-slate-950 text-white">
        <motion.img
          src={heroImage}
          alt="A modern video editing workstation with a timeline and color scopes on screen"
          className="absolute inset-0 h-full w-full scale-[1.03] object-cover object-center"
          initial={{ scale: 1.1, filter: "blur(7px)" }}
          animate={{ scale: 1.03, filter: "blur(1.5px)" }}
          transition={{ duration: 1.8, ease: [0.2, 0.8, 0.2, 1] }}
        />
        <div className="absolute inset-0 bg-[linear-gradient(90deg,rgba(7,13,25,.9)_0%,rgba(7,13,25,.66)_43%,rgba(7,13,25,.12)_78%),linear-gradient(0deg,rgba(7,13,25,.62)_0%,transparent_52%)]" />

        <header className="absolute inset-x-0 top-0 z-20 border-b border-white/20">
          <div className="mx-auto flex max-w-[1440px] items-center justify-between px-6 py-5 sm:px-10 lg:px-16">
            <a href="#top" className="flex items-center gap-3 font-semibold tracking-[-0.02em]">
              <span className="grid h-8 w-8 place-items-center border border-white/60 bg-white/10 backdrop-blur-sm"><Icon name="nodes" className="h-4 w-4" /></span>
              RAB / 1.2
            </a>
            <nav className="hidden items-center gap-7 text-sm text-white/80 sm:flex" aria-label="Main navigation">
              <a className="transition hover:text-white" href="#setup">Setup</a>
              <a className="transition hover:text-white" href="#connect">Connect</a>
              <a className="transition hover:text-white" href="#images">Images</a>
              <a className="transition hover:text-white" href="#editing">Editing</a>
              <a className="transition hover:text-white" href="#remotion">Remotion</a>
              <a className="transition hover:text-white" href="#help">Help</a>
            </nav>
          </div>
        </header>

        <div id="top" className="relative z-10 mx-auto flex h-full max-w-[1440px] items-end px-6 pb-14 pt-28 sm:px-10 sm:pb-20 lg:px-16 lg:pb-24">
          <div className="max-w-4xl">
            <motion.p initial={{ opacity: 0, y: 18 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.35, duration: 0.7 }} className="mb-4 text-xs font-semibold uppercase tracking-[0.24em] text-blue-200">
              Open source control for DaVinci Resolve
            </motion.p>
            <motion.h1 initial={{ opacity: 0, y: 24 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.48, duration: 0.8 }} className="font-display text-[clamp(4.5rem,11vw,9.5rem)] leading-[0.78] tracking-[-0.065em]">
              Resolve<br />AI Bridge
            </motion.h1>
            <motion.p initial={{ opacity: 0, y: 18 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.66, duration: 0.7 }} className="mt-8 max-w-xl text-base leading-7 text-slate-100 sm:text-xl sm:leading-8">
              A local MCP bridge that lets Claude, Codex, Antigravity, and other compatible AI tools work with the project open in Resolve. Nothing to edit, nothing to repaste each session.
            </motion.p>
            <motion.div initial={{ opacity: 0, y: 16 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.82, duration: 0.7 }} className="mt-8 flex flex-wrap gap-3">
              <a href="#setup" className="button-primary">Install the bridge <Icon name="arrow" /></a>
              <a href="#how" className="button-ghost">See how it works</a>
            </motion.div>
          </div>
        </div>
      </section>

      <section id="how" className="page-section py-24 sm:py-32">
        <Reveal>
          <SectionIntro number="00 / Read this first" title="One bridge. Two ways in." text="Nothing is uploaded to a bridge service. Resolve, the file queue, and your AI client's MCP process all stay on your computer." />
        </Reveal>
        <Reveal className="mt-16 grid gap-0 border-y border-slate-300 md:grid-cols-3">
          {[
            ["01", "MCP server", "Gives your AI a focused set of editing tools and returns Resolve's real answer, never a guess."],
            ["02a", "Direct attach", "The default. The MCP process talks to the open Resolve through Blackmagic's own scripting library, so nothing has to be started inside Resolve."],
            ["02b", "Console worker", "The fallback. A menu-started worker reads token-protected JSON from ~/.resolve-ai-bridge. No network port is opened."],
          ].map(([n, title, text], i) => (
            <div key={title} className={`py-8 md:px-8 ${i > 0 ? "border-t border-slate-300 md:border-l md:border-t-0" : ""}`}>
              <span className="font-mono text-xs text-blue-700">{n}</span>
              <h3 className="mt-7 text-xl font-semibold tracking-[-0.02em]">{title}</h3>
              <p className="mt-3 max-w-sm leading-7 text-slate-600">{text}</p>
            </div>
          ))}
        </Reveal>
        <Reveal className="mt-10 flex items-start gap-4 bg-[#e8edf5] px-5 py-5 sm:px-7">
          <Icon name="help" className="mt-0.5 h-5 w-5 shrink-0 text-blue-700" />
          <p className="max-w-4xl text-sm leading-6 text-slate-700"><strong>Important:</strong> both routes work on free DaVinci Resolve, and the bridge falls back automatically when a direct attach is refused. Resolve versions and operating systems vary, so the included doctor check is the source of truth on your machine. A successful web build does not prove that a given Resolve API call works on your exact Resolve version.</p>
        </Reveal>
      </section>

      <section id="setup" className="bg-white py-24 sm:py-32">
        <div className="page-section">
          <Reveal>
            <SectionIntro number="01 / Install" title="Set up the local runtime." text="You need DaVinci Resolve, Python 3.10 or newer, and an MCP-compatible AI client. Node.js is heavily recommended for the Remotion workflow later in this guide." />
          </Reveal>

          <Reveal className="mt-14 section-grid">
            <div>
              <p className="section-number">Choose your system</p>
              <div className="mt-4 inline-flex border border-slate-300 bg-[#f5f2ea] p-1" role="group" aria-label="Operating system">
                {(["mac", "windows"] as OS[]).map((item) => (
                  <button key={item} onClick={() => setOS(item)} className={`px-4 py-2 text-sm font-semibold transition ${os === item ? "bg-slate-950 text-white" : "text-slate-600 hover:text-slate-950"}`}>
                    {item === "mac" ? "macOS" : "Windows"}
                  </button>
                ))}
              </div>
            </div>
            <div className="max-w-3xl">
              <ol className="divide-y divide-slate-200 border-y border-slate-200">
                <li className="step-row"><span>1</span><div><h3>Download and keep the whole folder</h3><p>On GitHub choose Code, then Download ZIP. Extract it. Open <strong>00_START_HERE.html</strong> first. The installer needs the agent and bridge folders beside it.</p></div></li>
                <li className="step-row"><span>2</span><div><h3>Open a normal terminal in that folder</h3><p>On macOS, Control-click the folder and use New Terminal at Folder. On Windows, open the folder, click the address bar, type <code>powershell</code>, and press Enter.</p></div></li>
                <li className="step-row"><span>3</span><div><h3>Run the installer</h3><p>It creates a private runtime at <code>~/.resolve-ai-bridge</code>, a Python virtual environment, a persistent token, a filled MCP configuration, and the one-click Resolve menu entries.</p></div></li>
                <li className="step-row"><span>4</span><div><h3>Restart DaVinci Resolve once</h3><p>Resolve only looks for new Workspace &gt; Scripts entries while it starts up. After this single restart the launcher is permanent.</p></div></li>
              </ol>
              <div className="mt-6"><CopyBlock code={installCommands[os]} label={`${os === "mac" ? "macOS Terminal" : "Windows PowerShell"} - run from the downloaded folder`} /></div>
              <p className="mt-4 text-sm leading-6 text-slate-600">Wait for <strong>INSTALL COMPLETE</strong>, then follow the numbered steps it prints. The bridge never needs an inbound network port. The installer only downloads the Python MCP dependency.</p>
            </div>
          </Reveal>
        </div>
      </section>

      <section id="connect" className="page-section py-24 sm:py-32">
        <Reveal>
          <SectionIntro number="02 / Start Resolve" title="Open Resolve. That is normally the whole step." text="This version attaches to the running Resolve by itself. Nothing to edit, no user name to replace, and nothing to redo every time you launch the app. Two fallbacks are installed for you in case your Resolve build refuses a direct attach." />
        </Reveal>
        <Reveal className="mt-16 grid gap-0 border-y border-slate-300 md:grid-cols-3">
          {[
            ["Route 1 - default", "Just open Resolve", "Open Resolve and your project. The MCP server finds it. To switch the bridge off, disconnect or disable the MCP server in your AI client."],
            ["Route 2 - one-click start", "Workspace > Scripts", "Choose Workspace > Scripts > Resolve AI Bridge > Start AI Bridge. The worker starts directly; confirm with resolve_status. No Console paste is needed on the tested macOS Free 21.0.3.7 build."],
            ["Route 3 - fallback", "One portable line", "Paste the line below into Workspace > Console with the Py3 tab selected. It is the same text on every computer."],
          ].map(([n, title, text], i) => (
            <div key={title} className={`py-8 md:px-8 ${i > 0 ? "border-t border-slate-300 md:border-l md:border-t-0" : ""}`}>
              <span className="font-mono text-xs text-blue-700">{n}</span>
              <h3 className="mt-7 text-xl font-semibold tracking-[-0.02em]">{title}</h3>
              <p className="mt-3 max-w-sm leading-7 text-slate-600">{text}</p>
            </div>
          ))}
        </Reveal>
        <Reveal className="mt-14 section-grid">
          <div className="space-y-3 text-sm leading-6 text-slate-600">
            <p className="section-number">Nothing to personalise</p>
            <p>The old guide asked you to replace <code>YOUR_NAME</code> by hand. That step is gone. Python expands <code>~</code> to your own home folder inside Resolve, so this exact text is correct for every user on macOS, Windows, and Linux.</p>
            <p>Saved for you at <code>~/.resolve-ai-bridge/console-command.txt</code>.</p>
          </div>
          <div className="min-w-0 max-w-3xl">
            <CopyBlock code={consoleCommand} label="Resolve Python 3 Console - identical on macOS and Windows" />
            <div className="mt-5 border-l-2 border-blue-700 pl-5 text-sm leading-6 text-slate-600">
              <p>The menu worker keeps a separate script process alive while Resolve remains usable. The Console fallback returns after a short startup handshake. Stop it from <strong>Workspace &gt; Scripts &gt; Resolve AI Bridge &gt; Stop AI Bridge</strong>, or quit Resolve.</p>
            </div>
          </div>
        </Reveal>

        <Reveal className="mt-20 section-grid border-t border-slate-300 pt-12">
          <div>
            <p className="section-number">What success looks like</p>
            <div className="mt-5 flex items-center gap-3 text-sm font-semibold text-emerald-800"><span className="h-2.5 w-2.5 rounded-full bg-emerald-600" />BRIDGE READY</div>
          </div>
          <div className="max-w-3xl">
            <h3 className="text-2xl font-semibold tracking-[-0.025em]">Which route am I on?</h3>
            <p className="mt-3 leading-7 text-slate-600">Ask your AI to call <code>resolve_status</code>, or run <code>python3 tools/doctor.py</code>. Both report the live connection. A direct attach needs Resolve open and <strong>Preferences &gt; System &gt; General &gt; External scripting using</strong> set to <strong>Local</strong>. The installer already wrote a filled MCP configuration with real absolute paths and your token, so copy it rather than retyping it:</p>
            <div className="mt-6"><CopyBlock code={configExample} label="Shape only - copy your generated file" compact /></div>
            <p className="mt-4 text-sm leading-6 text-slate-600">Your filled copy is at <code>~/.resolve-ai-bridge/mcp-config.json</code>. Use absolute paths only, never <code>~</code> or a relative path.</p>
          </div>
        </Reveal>
      </section>

      <section className="bg-[#e9edf5] py-24 sm:py-32">
        <div className="page-section">
          <Reveal>
            <SectionIntro number="03 / Add your AI" title="Connect the MCP server." text="Choose your provider. Each one launches the same local server with stdio; only the settings screen is different." />
          </Reveal>
          <Reveal className="mt-14 section-grid">
            <div className="flex flex-col items-start gap-1" role="tablist" aria-label="AI provider">
              {(Object.keys(providers) as Provider[]).map((name) => (
                <button key={name} role="tab" aria-selected={provider === name} onClick={() => setProvider(name)} className={`provider-tab ${provider === name ? "provider-tab-active" : ""}`}>
                  {name}<Icon name="arrow" className="h-4 w-4" />
                </button>
              ))}
            </div>
            <div className="max-w-3xl min-h-[360px]">
              <AnimatePresence mode="wait">
                <motion.div key={provider} initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -8 }} transition={{ duration: 0.25 }}>
                  <p className="font-mono text-xs uppercase tracking-[0.16em] text-blue-700">{provider}</p>
                  <h3 className="mt-3 text-3xl font-semibold tracking-[-0.035em]">{providers[provider].title}</h3>
                  <ol className="mt-8 divide-y divide-slate-300 border-y border-slate-300">
                    {providers[provider].steps.map((step, index) => (
                      <li key={step} className="flex gap-5 py-5 text-sm leading-6 text-slate-700"><span className="font-mono text-xs text-blue-700">0{index + 1}</span><p>{step}</p></li>
                    ))}
                  </ol>
                </motion.div>
              </AnimatePresence>
            </div>
          </Reveal>
        </div>
      </section>

      <section className="page-section py-24 sm:py-32">
        <Reveal>
          <SectionIntro number="04 / Prove it works" title="Test before asking for a real edit." text="A one-minute check prevents the model from guessing when Resolve is closed or the wrong timeline is open." />
        </Reveal>
        <Reveal className="mt-14 grid gap-10 lg:grid-cols-[1fr_1.3fr]">
          <div className="space-y-7">
            {[
              ["Run doctor", os === "mac" ? "python3 tools/doctor.py" : "py tools/doctor.py"],
              ["Ask for status", "Call resolve_status and tell me the open project, timeline, and which transport you are using. Do not edit anything."],
              ["Make a safe edit", "Inspect the timeline. Add a blue marker at the current playhead named Bridge test, then verify it exists."],
            ].map(([title, text], index) => (
              <div key={title} className="grid grid-cols-[38px_1fr] gap-4 border-b border-slate-300 pb-7">
                <span className="grid h-9 w-9 place-items-center rounded-full bg-slate-950 font-mono text-xs text-white">{index + 1}</span>
                <div><h3 className="font-semibold">{title}</h3><p className="mt-2 break-words font-mono text-xs leading-6 text-slate-600">{text}</p></div>
              </div>
            ))}
          </div>
          <div className="bg-slate-950 p-7 text-white sm:p-10">
            <p className="font-mono text-xs uppercase tracking-[0.18em] text-blue-300">A better editing prompt</p>
            <blockquote className="mt-6 font-display text-2xl leading-snug tracking-[-0.02em] sm:text-3xl">&ldquo;First inspect the open timeline. Tell me your edit plan and any assumptions. Work in small steps, verify after each tool call, and do not delete clips or start a render without asking me.&rdquo;</blockquote>
            <p className="mt-8 border-t border-white/15 pt-6 text-sm leading-6 text-slate-300">The included Resolve editing skill teaches this inspect, plan, edit, verify loop. The MCP server also exposes a guide so capable clients can read the workflow before editing.</p>
          </div>
        </Reveal>
      </section>

      <section id="images" className="bg-white py-24 sm:py-32">
        <div className="page-section">
          <Reveal>
            <SectionIntro number="05 / Images and overlays" title="Hand your AI a picture and let it place it." text="Give any AI client an absolute path to a PNG, JPEG, TIFF, EXR, or other still and it can import the file, put it on the timeline for a real duration, and position it over your footage." />
          </Reveal>
          <Reveal className="mt-14 section-grid">
            <div className="space-y-5 text-sm leading-6 text-slate-600">
              <p className="section-number">Why a dedicated tool</p>
              <p>Appending a still like ordinary footage lands a single frame, because Resolve reports a still's length differently from a video clip. <code>add_image</code> asks for a duration in seconds, creates the video track it needs, and reports the length Resolve actually produced.</p>
              <p>Longer results get capped by <strong>Preferences &gt; Editing &gt; Standard still duration</strong> on some builds. The tool tells you when that happened instead of quietly succeeding.</p>
            </div>
            <div className="max-w-3xl">
              <CopyBlock code={imagePrompt} label="Prompt for any MCP client" />
              <div className="mt-8 grid gap-5 sm:grid-cols-3">
                {[
                  ["add_image", "Import and place one still with a duration, a track, an optional record frame, and an optional first position."],
                  ["set_clip_transform", "Move, scale, rotate, crop, fade, or blend any timeline item by id, in pixels or percentages of frame size."],
                  ["add_track", "Create the overlay tracks an image needs so footage on V1 stays visible underneath."],
                ].map(([title, text], index) => (
                  <div key={title} className="border-t border-slate-400 pt-4"><span className="font-mono text-xs text-blue-700">0{index + 1}</span><h4 className="mt-3 font-mono text-sm font-semibold">{title}</h4><p className="mt-2 text-sm leading-6 text-slate-600">{text}</p></div>
                ))}
              </div>
              <p className="mt-8 text-sm leading-6 text-slate-600">Generated images work the same way. Ask your AI to write the file to disk first, then pass that absolute path. For animated typography and designed motion, render it with Remotion below and import the video instead.</p>
            </div>
          </Reveal>
        </div>
      </section>

      <section id="editing" className="page-section py-24 sm:py-32">
        <div className="page-section">
          <Reveal>
            <SectionIntro number="06 / Timeline editing" title="Scale, animate, and cut the clips you already placed." text="Point your AI at a clip by its id, such as V1.2, or just say the clip under the playhead. It can reframe it, push in or pull out over time, and razor it in two, so the repetitive parts of an edit are automated." />
          </Reveal>
          <Reveal className="mt-14 section-grid">
            <div className="space-y-5 text-sm leading-6 text-slate-600">
              <p className="section-number">What is new in 1.2</p>
              <p><code>set_clip_transform</code> now scales on both axes, adds scaling mode, resize filter, retime and motion-estimation controls, and accepts <code>item_id="playhead"</code> so the AI can act on the clip you are looking at.</p>
              <p><code>animate_zoom</code> builds a Fusion composition on the clip and keyframes its size, so a push-in actually plays back. It reports whether keyframes were created and falls back to a static zoom on builds that refuse scripted keyframes, rather than pretending.</p>
              <p><code>split_clip</code> cuts a clip in two at a frame, a timecode, or the playhead. Resolve's scripting API has no razor, so the clip is rebuilt as two pieces that keep their source frames and transform. Color grades and Fusion comps on the original are not copied onto the halves, and the reply says so.</p>
            </div>
            <div className="max-w-3xl">
              <CopyBlock code={editingPrompt} label="Prompt for any MCP client" />
              <div className="mt-8 grid gap-5 sm:grid-cols-3">
                {[
                  ["set_clip_transform", "Static reframe: scale, pan, tilt, rotate, crop, fade, blend, scaling mode, and resize filter, by id or at the playhead."],
                  ["animate_zoom", "Animated scale over time via a Fusion comp. Set start and end zoom and the frame range within the clip."],
                  ["split_clip", "Razor a clip in two at a frame, timecode, or the playhead, rebuilt from Resolve's documented append API."],
                ].map(([title, text], index) => (
                  <div key={title} className="border-t border-slate-400 pt-4"><span className="font-mono text-xs text-blue-700">0{index + 1}</span><h4 className="mt-3 font-mono text-sm font-semibold">{title}</h4><p className="mt-2 text-sm leading-6 text-slate-600">{text}</p></div>
                ))}
              </div>
              <p className="mt-8 text-sm leading-6 text-slate-600">These edits were written against Blackmagic's documented scripting API for free DaVinci Resolve. Because Resolve exposes no razor and cannot keyframe Edit-page sizing directly, cuts and animations are synthesised and reported honestly. Verify with <code>timeline_overview</code> and the doctor check on your own build.</p>
            </div>
          </Reveal>
        </div>
      </section>

      <section id="remotion" className="bg-[#f0e7d8] py-24 sm:py-32">
        <div className="page-section">
          <Reveal>
            <SectionIntro number="06 / Heavily recommended" title="Use Remotion for stronger motion design." text="Resolve scripting is useful for timeline organization, stills, and repeatable edits. Remotion gives your coding agent a much better language for designed titles, explainers, product scenes, and precise animation." />
          </Reveal>
          <Reveal className="mt-14 section-grid">
            <div className="space-y-5 text-sm leading-6 text-slate-600">
              <div className="flex h-11 w-11 items-center justify-center bg-blue-700 text-white"><Icon name="spark" /></div>
              <p><strong className="text-slate-950">Node.js is heavily recommended, not required by the bridge.</strong> Install the current Node.js LTS release from nodejs.org. It includes npm and npx.</p>
              <p>Confirm the install in a new terminal:</p>
              <p className="font-mono text-xs text-slate-950">node --version<br />npm --version</p>
            </div>
            <div className="max-w-3xl">
              <h3 className="text-2xl font-semibold tracking-[-0.025em]">Exact Remotion setup</h3>
              <p className="mt-3 leading-7 text-slate-600">Run these commands in a normal terminal, not in the Resolve Console. The first command installs the official <strong>remotion-dev/skills</strong> instructions so supported coding agents use the correct Remotion APIs and animation patterns.</p>
              <div className="mt-6"><CopyBlock code={remotionCommands} label="Normal terminal - Node.js required" /></div>
              <div className="mt-8 grid gap-5 sm:grid-cols-3">
                {[
                  ["Design", "Open your AI in the my-video folder and ask for a composition with exact duration, aspect ratio, copy, and style."],
                  ["Preview", "Keep npm run dev open. Review the result in Remotion Studio and request focused revisions."],
                  ["Render", "Ask the agent for the composition ID, then render an MP4 into out/video.mp4."],
                ].map(([title, text], index) => (
                  <div key={title} className="border-t border-slate-400 pt-4"><span className="font-mono text-xs text-blue-700">0{index + 1}</span><h4 className="mt-3 font-semibold">{title}</h4><p className="mt-2 text-sm leading-6 text-slate-600">{text}</p></div>
                ))}
              </div>
              <div className="mt-8"><CopyBlock code={'npx remotion render <CompositionId> out/video.mp4'} label="Render the approved composition" compact /></div>
            </div>
          </Reveal>
          <Reveal className="mt-16 section-grid border-t border-slate-400 pt-10">
            <p className="section-number">Bring it into Resolve</p>
            <div className="max-w-3xl">
              <h3 className="text-2xl font-semibold tracking-[-0.025em]">Let each tool do the job it is good at.</h3>
              <p className="mt-3 leading-7 text-slate-600">Remotion renders the designed clip. Resolve handles footage, audio, color, review, and final delivery. After rendering, use this prompt:</p>
              <blockquote className="mt-6 border-l-2 border-blue-700 pl-5 font-display text-xl leading-8 text-slate-800">&ldquo;Import the absolute file path to out/video.mp4 into the current media pool. Show me the timeline overview, then ask where I want it placed before appending it.&rdquo;</blockquote>
            </div>
          </Reveal>
        </div>
      </section>

      <section id="help" className="page-section py-24 sm:py-32">
        <Reveal>
          <SectionIntro number="07 / Help" title="Common questions, plain answers." text="Start with the exact error, not a reinstall. The connection, token, MCP process, and Console worker can each be checked separately." />
        </Reveal>
        <Reveal className="mt-14 section-grid">
          <div>
            <p className="section-number">Troubleshooting order</p>
            <p className="mt-4 max-w-xs text-sm leading-6 text-slate-600">Run doctor with Resolve open. Read which route it reports. Then confirm your provider uses the generated absolute paths and matching token.</p>
          </div>
          <div className="max-w-3xl border-t border-slate-300">
            {faq.map((item, index) => (
              <div key={item.q} className="border-b border-slate-300">
                <button className="flex w-full items-center justify-between gap-6 py-6 text-left font-semibold" onClick={() => setOpenFaq(openFaq === index ? -1 : index)} aria-expanded={openFaq === index}>
                  {item.q}<span className={`text-2xl font-light transition-transform ${openFaq === index ? "rotate-45" : ""}`}>+</span>
                </button>
                <AnimatePresence initial={false}>
                  {openFaq === index && <motion.div initial={{ height: 0, opacity: 0 }} animate={{ height: "auto", opacity: 1 }} exit={{ height: 0, opacity: 0 }} className="overflow-hidden"><p className="max-w-2xl pb-6 text-sm leading-7 text-slate-600">{item.a}</p></motion.div>}
                </AnimatePresence>
              </div>
            ))}
          </div>
        </Reveal>

        <Reveal className="mt-20 bg-blue-700 px-6 py-10 text-white sm:px-10 lg:px-14 lg:py-14">
          <div className="grid gap-8 lg:grid-cols-[.7fr_1.3fr]">
            <div><Icon name="help" className="h-7 w-7" /><h3 className="mt-5 font-display text-3xl tracking-[-0.03em]">If you still need help</h3></div>
            <div>
              <p className="max-w-2xl leading-7 text-blue-50">Your provider can inspect local files and fix its own MCP entry. Paste this complete request into Antigravity, Claude Code, Codex, or another coding agent:</p>
              <div className="mt-6"><CopyBlock code={'Read 00_START_HERE.html and README.md in this project. Then run tools/doctor.py, inspect ~/.resolve-ai-bridge/mcp-config.json, and configure your own MCP settings for resolve-ai-bridge. Preserve my existing MCP servers. Do not change or expose the token. Test with resolve_status only and explain any error in simple steps.'} label="Provider help prompt" compact /></div>
            </div>
          </div>
        </Reveal>
      </section>

      <footer className="bg-slate-950 px-6 py-14 text-white sm:px-10 lg:px-16">
        <div className="mx-auto flex max-w-[1440px] flex-col justify-between gap-10 sm:flex-row sm:items-end">
          <div><p className="font-display text-4xl tracking-[-0.045em]">Resolve AI Bridge</p><p className="mt-3 text-sm text-slate-400">Local, inspectable, MIT-licensed.</p></div>
          <div className="text-left text-xs leading-6 text-slate-500 sm:text-right"><p>Start with 00_START_HERE.html</p><p>DaVinci Resolve and Remotion are trademarks of their respective owners.</p></div>
        </div>
      </footer>
    </main>
  );
}