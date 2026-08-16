"use client";

import { FormEvent, useEffect, useState } from "react";
import type { Session } from "@supabase/supabase-js";
import Dashboard from "./Dashboard";
import { LearnPublicPreview } from "./components/learn/LearnPage";
import { supabase } from "./supabase";

const API = process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:8000/api";

export default function InvestmentApp() {
  const [session, setSession] = useState<Session | null>(null);
  const [ready, setReady] = useState(!supabase);
  const [mode, setMode] = useState<"login" | "signup">("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const [currentPath, setCurrentPath] = useState("/");

  useEffect(() => {
    setCurrentPath(window.location.pathname);
    const onPopState=()=>setCurrentPath(window.location.pathname);
    window.addEventListener("popstate",onPopState);
    if (!supabase) return () => window.removeEventListener("popstate",onPopState);
    void supabase.auth.getSession().then(({ data }) => { setSession(data.session); setReady(true); });
    const { data } = supabase.auth.onAuthStateChange((_event, next) => setSession(next));
    return () => { data.subscription.unsubscribe(); window.removeEventListener("popstate",onPopState); };
  }, []);

  function showAccess(){window.history.pushState({},"","/#access");setCurrentPath("/");window.requestAnimationFrame(()=>document.getElementById("access")?.scrollIntoView({behavior:"smooth"}));}

  async function authenticate(event: FormEvent) {
    event.preventDefault();
    if (!supabase) { setMessage("Add the Supabase URL and publishable key to .env.local, then restart the web app."); return; }
    setBusy(true); setMessage("");
    const result = mode === "login"
      ? await supabase.auth.signInWithPassword({ email, password })
      : await supabase.auth.signUp({ email, password });
    setBusy(false);
    if (result.error) setMessage(result.error.message);
    else if (mode === "signup" && !result.data.session) setMessage("Check your email to confirm your account, then sign in.");
  }

  if (!ready) return <div className="auth-loading">Opening your research workspace…</div>;
  if (session) return <Dashboard accessToken={session.access_token} email={session.user.email || "Investor"} onSignOut={() => {
    void supabase?.auth.signOut();
  }} />;
  if(currentPath.startsWith("/learn"))return <LearnPublicPreview apiUrl={API} onSignIn={showAccess}/>;

  return <main className="landing-shell">
    <header className="landing-nav"><a className="landing-brand" href="#top"><span>EA</span><b>EagleEyes AI</b></a><nav><a href="#method">Method</a><a href="#research">Research</a><a href="/learn">Learn</a><a href="#safety">Safety</a></nav><button onClick={() => document.getElementById("access")?.scrollIntoView({ behavior: "smooth" })}>Sign in</button></header>
    <section className="landing-hero" id="top"><div className="landing-copy"><span className="landing-kicker">Portfolio research, grounded in evidence</span><h1>Understand what your portfolio is betting on.</h1><p>Connect macro conditions, prediction-market probabilities, company fundamentals, and historical regimes—then compare transparent allocation alternatives without handing over control.</p><div><button className="landing-primary" onClick={() => document.getElementById("access")?.scrollIntoView({ behavior: "smooth" })}>Open your workspace</button><a href="#method">See how it works</a></div><small>Decision support only · no brokerage connection · no trade execution</small></div><div className="landing-orbit"><div><span>Current lens</span><strong>Rates × Inflation</strong><b>Scenario-aware</b></div><i /><i /><i /></div></section>
    <section className="landing-factor-row" id="method"><article><b>01</b><h2>Macro expectations</h2><p>Rates, inflation, growth, labor, and credit—with dates, confidence, and an explicit distinction between change and surprise.</p></article><article><b>02</b><h2>Company evidence</h2><p>Prices, fundamentals, valuation, industry context, news, and relevant prediction markets for your own holdings and watchlist.</p></article><article><b>03</b><h2>Transparent alternatives</h2><p>Risk-Controlled, Balanced, and Goal-Tilted ranges with assumptions, backtests, taxes, turnover, and constraints beside every result.</p></article></section>
    <section className="landing-research" id="research"><div><span>Built around your questions</span><h2>A workbench, not a generic market homepage.</h2><p>Choose the stocks and factor widgets you care about. Your holdings, saved research settings, analysis history, and cited conversations live in your private workspace.</p><ul><li>Adjustable macro and research widgets</li><li>Point-in-time regime library and walk-forward tests</li><li>Gemini assistant grounded only in stored evidence</li></ul></div><div className="landing-stack"><span>Prediction markets</span><span>FRED macro history</span><span>Corporate-action-adjusted prices</span><span>SEC fundamentals</span><span>Portfolio constraints</span></div></section>
    <section className="access-section" id="access"><div><span>Private research workspace</span><h2>{mode === "login" ? "Welcome back." : "Create your workspace."}</h2><p>Supabase authentication keeps each portfolio, profile, widget layout, analysis, and conversation attached to its owner.</p></div><form data-testid="auth-form" onSubmit={authenticate}><label>Email<input data-testid="auth-email" type="email" required value={email} onChange={event => setEmail(event.target.value)} placeholder="you@example.com" /></label><label>Password<input data-testid="auth-password" type="password" required minLength={6} value={password} onChange={event => setPassword(event.target.value)} placeholder="At least 6 characters" /></label>{message && <p className="auth-message">{message}</p>}<button data-testid="auth-submit" className="landing-primary" disabled={busy}>{busy ? "Please wait…" : mode === "login" ? "Sign in" : "Create account"}</button><button type="button" className="mode-switch" onClick={() => { setMode(mode === "login" ? "signup" : "login"); setMessage(""); }}>{mode === "login" ? "New here? Create an account" : "Already have an account? Sign in"}</button></form></section>
    <footer id="safety"><div className="landing-brand"><span>EA</span><b>EagleEyes AI</b></div><p>Research estimates are uncertain and are not investment, tax, or legal advice. Trading remains disabled.</p></footer>
  </main>;
}
