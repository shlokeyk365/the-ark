import { useEffect, useState } from "react";
import { App as DashboardApp } from "./DashboardApp";
import { LandingScenarioMap } from "./components/LandingScenarioMap";
import {
  ArrowDown,
  ArrowUpRight,
  Menu,
  X,
} from "lucide-react";

const navItems = [
  ["Platform", "#platform"],
  ["How it works", "#model"],
  ["Scenarios", "#response"],
  ["About", "#about"],
];

function TechnicalButton({
  children,
  href,
  secondary = false,
}: {
  children: React.ReactNode;
  href: string;
  secondary?: boolean;
}) {
  return (
    <a
      href={href}
      className={`group inline-flex min-h-11 items-center justify-center gap-4 border px-5 font-mono text-[11px] font-bold uppercase tracking-[0.14em] transition-colors duration-300 sm:text-xs ${
        secondary
          ? "border-white/20 bg-black/20 text-white hover:border-[#7396a8] hover:bg-[#7396a8]/10"
          : "border-[#7396a8] bg-[#7396a8]/10 text-white hover:bg-[#7396a8] hover:text-[#080a0c]"
      }`}
    >
      {children}
      <ArrowUpRight className="size-4 transition-transform duration-300 group-hover:translate-x-0.5 group-hover:-translate-y-0.5" />
    </a>
  );
}

function Brand() {
  return (
    <a href="#top" className="flex items-center gap-2" aria-label="ARK home">
      <img
        src="/assets/ark-longboat-logo.png"
        alt=""
        className="h-8 w-auto max-w-12 shrink-0 object-contain opacity-95"
      />
      <span className="font-mono text-lg font-bold tracking-[0.2em]">ARK</span>
    </a>
  );
}

function LandingPage() {
  const [menuOpen, setMenuOpen] = useState(false);

  useEffect(() => {
    document.documentElement.classList.add("landing-mode");
    return () => document.documentElement.classList.remove("landing-mode");
  }, []);

  return (
    <main id="top" className="landing-page bg-[#050607] text-[#f1f3f2]">
      <header className="fixed inset-x-0 top-0 z-50 border-b border-white/10 bg-[#050607]/65 backdrop-blur-md">
        <div className="mx-auto flex h-[72px] max-w-[1600px] items-center justify-between px-5 sm:px-8 lg:px-16">
          <Brand />
          <nav className="hidden items-center gap-1 lg:flex" aria-label="Primary navigation">
            {navItems.map(([label, href], index) => (
              <a
                key={label}
                href={href}
                className={`px-4 py-2 font-mono text-[11px] uppercase tracking-[0.1em] transition-colors hover:text-white ${
                  index === 0 ? "text-[#87aabc]" : "text-[#929aa1]"
                }`}
              >
                {label}
              </a>
            ))}
          </nav>
          <div className="hidden lg:block">
            <TechnicalButton href="/command-center" secondary>
              Enter command center
            </TechnicalButton>
          </div>
          <button
            className="grid size-11 place-items-center border border-white/20 lg:hidden"
            onClick={() => setMenuOpen((open) => !open)}
            aria-expanded={menuOpen}
            aria-label={menuOpen ? "Close menu" : "Open menu"}
          >
            {menuOpen ? <X className="size-5" /> : <Menu className="size-5" />}
          </button>
        </div>
        {menuOpen && (
          <nav className="border-t border-white/10 bg-[#080a0c] px-5 py-5 lg:hidden" aria-label="Mobile navigation">
            {navItems.map(([label, href]) => (
              <a
                key={label}
                href={href}
                onClick={() => setMenuOpen(false)}
                className="block border-b border-white/10 py-4 font-mono text-xs uppercase tracking-[0.14em] text-[#c4c9cc]"
              >
                {label}
              </a>
            ))}
          </nav>
        )}
      </header>

      <section className="relative flex min-h-[100svh] items-end" aria-labelledby="hero-title">
        <video
          className="absolute inset-0 size-full object-cover"
          src="/assets/hero-video.mp4"
          autoPlay
          muted
          loop
          playsInline
          aria-hidden="true"
        />
        <div className="hero-scrim absolute inset-0" />
        <div className="relative z-10 mx-auto w-full max-w-[1600px] px-5 pb-24 pt-40 sm:px-8 sm:pb-28 lg:px-20 lg:pb-32">
          <div className="max-w-[760px]">
            <p className="eyebrow">Real-time disaster response world model</p>
            <h1 id="hero-title" className="mt-5 max-w-[720px] text-[clamp(2.75rem,5.1vw,4.75rem)] font-light leading-[1.02]">
              See what becomes unreachable next.
            </h1>
            <p className="mt-6 max-w-[660px] text-base leading-7 text-[#b0b6bb] sm:text-lg">
              ARK models the evolving disaster, the infrastructure around it, and the consequences of every response decision.
            </p>
            <div className="mt-8 flex flex-wrap gap-3">
              <TechnicalButton href="#platform">Explore ARK</TechnicalButton>
              <TechnicalButton href="#response" secondary>Watch the system</TechnicalButton>
            </div>
          </div>
        </div>
        <a
          href="#platform"
          className="absolute bottom-6 left-1/2 z-10 hidden -translate-x-1/2 flex-col items-center gap-2 font-mono text-[10px] uppercase tracking-[0.16em] text-[#a4abb0] sm:flex"
        >
          Scroll to explore
          <ArrowDown className="size-4" />
        </a>
      </section>

      <section id="platform" className="border-y border-[#303840] bg-[#090b0d]">
        <div className="mx-auto grid min-h-[500px] max-w-[1600px] items-center gap-12 px-5 py-24 sm:px-8 lg:grid-cols-[1.3fr_0.7fr] lg:px-20 lg:py-28">
          <h2 className="max-w-[950px] text-[clamp(2.4rem,4.5vw,4.3rem)] font-light leading-[1.12]">
            Flood response is not only about where the water goes.
          </h2>
          <div className="max-w-md lg:justify-self-end">
            <p className="text-base leading-7 text-[#929aa1]">
              It is about how conditions cascade through roads, hospitals, power, and every team moving through the field.
            </p>
            <div className="mt-7">
              <TechnicalButton href="#response" secondary>Navigate to human response</TechnicalButton>
            </div>
          </div>
        </div>
      </section>

      <section id="response" className="relative flex min-h-[82svh] items-end border-b border-[#303840]" aria-labelledby="response-title">
        <video
          className="absolute inset-0 size-full object-cover object-center"
          src="/assets/rescue-video.mp4"
          autoPlay
          muted
          loop
          playsInline
          aria-hidden="true"
        />
        <div className="rescue-scrim absolute inset-0" />
        <div className="relative z-10 mx-auto w-full max-w-[1600px] px-5 pb-16 sm:px-8 sm:pb-20 lg:px-20 lg:pb-24">
          <div className="max-w-[760px]">
            <p className="eyebrow text-[#bdd0d9]">Helicopter flood rescue / Live scenario 04</p>
            <h2 id="response-title" className="mt-4 text-[clamp(2.4rem,4.2vw,4rem)] font-light leading-[1.06]">
              When the road disappears, the mission changes with it.
            </h2>
            <p className="mt-5 max-w-xl text-base leading-7 text-[#d0d4d6]">
              ARK re-evaluates access, risk, and rescue capacity as the environment changes, keeping the operational picture current.
            </p>
          </div>
        </div>
      </section>

      <section id="model" className="bg-[#111417] py-24 sm:py-28 lg:py-32" aria-labelledby="model-title">
        <div className="mx-auto max-w-[1600px] px-5 sm:px-8 lg:px-20">
          <div className="max-w-[760px]">
            <p className="eyebrow text-[#87aabc]">Integrated situational intelligence</p>
            <h2 id="model-title" className="mt-4 text-[clamp(2.25rem,3.5vw,3.25rem)] font-light leading-tight">
              One model for a changing world.
            </h2>
            <p className="mt-5 text-base leading-7 text-[#929aa1]">
              ARK continuously connects environmental conditions, infrastructure networks, rescue assets, and field intelligence into a single co-dependent operational picture.
            </p>
          </div>

          <div className="model-frame landing-map-frame relative mt-14 aspect-[16/9] min-h-[520px] overflow-hidden border border-[#364049] bg-[#050607]">
            <LandingScenarioMap />
          </div>
        </div>
      </section>

      <section id="command" className="border-t border-[#303840] bg-[#07090b]" aria-labelledby="command-title">
        <div className="mx-auto grid min-h-[650px] max-w-[1600px] items-center gap-14 px-5 py-24 sm:px-8 lg:grid-cols-[1fr_0.85fr] lg:px-20">
          <div>
            <p className="eyebrow text-[#87aabc]">Operational command / Ready</p>
            <h2 id="command-title" className="mt-5 max-w-[760px] text-[clamp(2.8rem,5.4vw,5.5rem)] font-light leading-[1.02]">
              Turn uncertainty into a decision.
            </h2>
          </div>
          <div className="border-l border-[#3b4650] pl-6 sm:pl-10 lg:pl-14">
            <p className="max-w-lg text-lg leading-8 text-[#9da4aa]">
              Enter a live environment where forecasts, infrastructure dependencies, and response assets resolve into one actionable view.
            </p>
            <div className="mt-8">
              <TechnicalButton href="/command-center">Enter command center</TechnicalButton>
            </div>
          </div>
        </div>
      </section>

      <footer id="about" className="border-t border-[#303840] bg-[#111417]">
        <div className="mx-auto flex max-w-[1600px] flex-col gap-10 px-5 py-10 sm:px-8 lg:flex-row lg:items-center lg:justify-between lg:px-20">
          <Brand />
          <nav className="flex flex-wrap gap-x-6 gap-y-3" aria-label="Footer navigation">
            {["Platform", "Scenarios", "Intelligence", "Documentation", "GitHub", "Contact"].map((item) => (
              <a key={item} href="#top" className="text-xs text-[#8f979d] transition-colors hover:text-white">{item}</a>
            ))}
          </nav>
          <div className="flex flex-col gap-2 font-mono text-[10px] uppercase tracking-[0.08em] text-[#8f979d] sm:flex-row sm:gap-5">
            <span className="flex items-center gap-2"><span className="size-1.5 bg-[#83a899]" />Model status: Operational</span>
            <span>Last updated: Live</span>
          </div>
        </div>
      </footer>
    </main>
  );
}

function App() {
  return window.location.pathname === "/command-center" ? <DashboardApp /> : <LandingPage />;
}

export default App;
