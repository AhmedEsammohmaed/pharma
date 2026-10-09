"use client";

import { useEffect, useState, type FormEvent, type ReactNode } from "react";
import Link from "next/link";
import type { Session } from "@supabase/supabase-js";

import { ApiError, apiFetch, type Membership, type Profile } from "@/lib/api";
import { isSupabaseConfigured } from "@/lib/env";
import { createClient } from "@/lib/supabase/client";
import ProcurementWorkspace from "@/components/procurement-workspace";

type Section = "Overview" | "Inventory" | "Orders" | "Suppliers" | "Analytics" | "Reports" | "AI Copilot";
type IconName = "overview" | "inventory" | "orders" | "suppliers" | "analytics" | "reports" | "copilot" | "settings" | "search" | "bell" | "chevron" | "arrow" | "plus" | "download" | "clock" | "spark" | "dots" | "filter" | "check" | "menu";

const iconShapes: Record<IconName, ReactNode> = {
  overview: <><rect x="3.5" y="3.5" width="7" height="7" rx="1.5" /><rect x="13.5" y="3.5" width="7" height="7" rx="1.5" /><rect x="3.5" y="13.5" width="7" height="7" rx="1.5" /><rect x="13.5" y="13.5" width="7" height="7" rx="1.5" /></>,
  inventory: <><path d="m12 3 8.5 4.5v9L12 21l-8.5-4.5v-9L12 3Z" /><path d="m3.8 7.6 8.2 4.5 8.2-4.5M12 12.1V21" /></>,
  orders: <><path d="M5 4.5h14v16H5z" /><path d="M8.5 8.5h7M8.5 12h7M8.5 15.5h4" /><path d="M9 4.5V3h6v1.5" /></>,
  suppliers: <><path d="M3 7h11v11H3zM14 11h4l3 3v4h-7z" /><circle cx="7" cy="19" r="1.5" /><circle cx="18" cy="19" r="1.5" /><path d="M6 10h5M6 13h3" /></>,
  analytics: <><path d="M4 19.5h16" /><path d="M6.5 16v-4M11.5 16V7M16.5 16v-7" /><path d="m5.5 8 5-3 5 2 3-3" /></>,
  reports: <><path d="M6 3.5h8l4 4v13H6z" /><path d="M14 3.5v4h4M9 12h6M9 15.5h6" /></>,
  copilot: <><path d="m12 3 1.7 5.3L19 10l-5.3 1.7L12 17l-1.7-5.3L5 10l5.3-1.7L12 3Z" /><path d="m19 15 .9 2.1L22 18l-2.1.9L19 21l-.9-2.1L16 18l2.1-.9L19 15Z" /></>,
  settings: <><circle cx="12" cy="12" r="3" /><path d="m19.4 15 .1.1a1.7 1.7 0 0 1-2.4 2.4l-.1-.1a1.7 1.7 0 0 0-2.9 1.2v.2a1.7 1.7 0 0 1-3.4 0v-.2a1.7 1.7 0 0 0-2.9-1.2l-.1.1a1.7 1.7 0 0 1-2.4-2.4l.1-.1a1.7 1.7 0 0 0-1.2-2.9H4a1.7 1.7 0 0 1 0-3.4h.2a1.7 1.7 0 0 0 1.2-2.9l-.1-.1a1.7 1.7 0 0 1 2.4-2.4l.1.1a1.7 1.7 0 0 0 2.9-1.2V4a1.7 1.7 0 0 1 3.4 0v.2a1.7 1.7 0 0 0 2.9 1.2l.1-.1a1.7 1.7 0 0 1 2.4 2.4l-.1.1a1.7 1.7 0 0 0 1.2 2.9h.2a1.7 1.7 0 0 1 0 3.4h-.2a1.7 1.7 0 0 0-1.2.9Z" /></>,
  search: <><circle cx="10.8" cy="10.8" r="6.3" /><path d="m16 16 4.5 4.5" /></>,
  bell: <><path d="M18 9a6 6 0 0 0-12 0c0 7-3 7-3 9h18c0-2-3-2-3-9ZM10 21h4" /></>,
  chevron: <path d="m9 18 6-6-6-6" />,
  arrow: <><path d="M5 12h14M13 6l6 6-6 6" /></>,
  plus: <><path d="M12 5v14M5 12h14" /></>,
  download: <><path d="M12 3v12M7 10l5 5 5-5" /><path d="M5 20h14" /></>,
  clock: <><circle cx="12" cy="12" r="9" /><path d="M12 7v5l3.5 2" /></>,
  spark: <><path d="m12 3 1.7 5.3L19 10l-5.3 1.7L12 17l-1.7-5.3L5 10l5.3-1.7L12 3Z" /></>,
  dots: <><circle cx="5" cy="12" r="1" /><circle cx="12" cy="12" r="1" /><circle cx="19" cy="12" r="1" /></>,
  filter: <><path d="M4 6h16M7 12h10m-7 6h4" /></>,
  check: <path d="m5 12 4 4L19 6" />,
  menu: <><path d="M4 7h16M4 12h16M4 17h16" /></>,
};

function Icon({ name, size = 20, strokeWidth = 1.8 }: { name: IconName; size?: number; strokeWidth?: number }) {
  return <svg aria-hidden="true" width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={strokeWidth} strokeLinecap="round" strokeLinejoin="round">{iconShapes[name]}</svg>;
}

const navigation: { label: Section; icon: IconName }[] = [
  { label: "Overview", icon: "overview" },
  { label: "Inventory", icon: "inventory" },
  { label: "Orders", icon: "orders" },
  { label: "Suppliers", icon: "suppliers" },
  { label: "Analytics", icon: "analytics" },
  { label: "Reports", icon: "reports" },
];

type Product = { name: string; subtitle: string; sku: string; stock: number; reorder: number; unit: string; status: "Healthy" | "Low stock" | "Critical"; category: string };
const products: Product[] = [
  { name: "Panadol Advance", subtitle: "Paracetamol · 500 mg", sku: "PH-10482", stock: 18, reorder: 60, unit: "boxes", status: "Critical", category: "Pain relief" },
  { name: "Augmentin", subtitle: "Amoxicillin / clavulanate · 1 g", sku: "PH-21039", stock: 34, reorder: 50, unit: "boxes", status: "Low stock", category: "Antibiotics" },
  { name: "Cataflam", subtitle: "Diclofenac potassium · 50 mg", sku: "PH-08731", stock: 42, reorder: 40, unit: "boxes", status: "Healthy", category: "Pain relief" },
  { name: "Nexium", subtitle: "Esomeprazole · 40 mg", sku: "PH-19104", stock: 26, reorder: 45, unit: "boxes", status: "Low stock", category: "Digestive health" },
  { name: "Vitamin D3", subtitle: "Cholecalciferol · 5000 IU", sku: "PH-30215", stock: 96, reorder: 30, unit: "bottles", status: "Healthy", category: "Vitamins" },
  { name: "Zyrtec", subtitle: "Cetirizine · 10 mg", sku: "PH-11608", stock: 12, reorder: 35, unit: "boxes", status: "Critical", category: "Allergy" },
];

const demoOrders = [
  { id: "ORD-2841", customer: "Walk-in · 14:32", items: "3 items", amount: "EGP 485.00", status: "Completed", date: "Today, 2:32 PM" },
  { id: "ORD-2840", customer: "Mariam Hassan", items: "2 items", amount: "EGP 320.00", status: "Ready", date: "Today, 2:18 PM" },
  { id: "ORD-2839", customer: "Omar Khaled", items: "5 items", amount: "EGP 1,125.00", status: "Processing", date: "Today, 1:56 PM" },
  { id: "ORD-2838", customer: "Walk-in · 13:41", items: "1 item", amount: "EGP 95.00", status: "Completed", date: "Today, 1:41 PM" },
  { id: "ORD-2837", customer: "Nour Adel", items: "4 items", amount: "EGP 760.00", status: "Cancelled", date: "Today, 1:22 PM" },
];

function downloadCsv(filename: string, rows: string[][]) {
  const csv = rows.map((row) => row.map((cell) => `"${cell.replaceAll('"', '""')}"`).join(",")).join("\n");
  const url = URL.createObjectURL(new Blob([csv], { type: "text/csv;charset=utf-8" }));
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  anchor.click();
  URL.revokeObjectURL(url);
}

function DemoTag() {
  return <span className="demo-tag"><span className="demo-tag-dot" /> DEMO DATA</span>;
}

function PageHeading({ eyebrow, title, description, actions }: { eyebrow: string; title: string; description: string; actions?: ReactNode }) {
  return <div className="page-heading"><div><p className="eyebrow">{eyebrow}</p><h1>{title}</h1><p className="page-description">{description}</p></div>{actions ? <div className="heading-actions">{actions}</div> : null}</div>;
}

function MetricCard({ label, value, change, icon, tone, note }: { label: string; value: string; change: string; icon: IconName; tone: string; note: string }) {
  return <article className="metric-card"><div className="metric-top"><span className={`metric-icon ${tone}`}><Icon name={icon} size={18} /></span>{change ? <span className="metric-change"><span>↗</span> {change}</span> : null}</div><p className="metric-label">{label}</p><div className="metric-value-row"><strong>{value}</strong><span className="metric-note">{note}</span></div></article>;
}

function RevenueChart() {
  const data = [46, 56, 48, 66, 57, 72, 64, 85, 72, 91, 74, 100, 82, 89, 76, 94, 83, 112, 96, 119, 102, 126, 109, 134, 118, 140, 122, 151, 132, 164];
  const points = data.map((value, index) => `${(index / (data.length - 1)) * 680},${170 - value}`).join(" ");
  const areaPoints = `0,170 ${points} 680,170`;
  return <div className="chart-wrap"><div className="chart-y-labels"><span>EGP 20k</span><span>EGP 15k</span><span>EGP 10k</span><span>EGP 5k</span></div><svg className="revenue-chart" viewBox="0 0 680 180" preserveAspectRatio="none" role="img" aria-label="Sample revenue trend rising over the last 30 days"><defs><linearGradient id="chart-fill" x1="0" x2="0" y1="0" y2="1"><stop offset="0%" stopColor="#16a584" stopOpacity=".2" /><stop offset="100%" stopColor="#16a584" stopOpacity="0" /></linearGradient></defs><path className="chart-gridline" d="M0 22H680M0 64H680M0 106H680M0 148H680" /><polygon points={areaPoints} fill="url(#chart-fill)" /><polyline points={points} fill="none" stroke="#10866e" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round" vectorEffect="non-scaling-stroke" /><circle cx="680" cy="6" r="4.5" fill="#fff" stroke="#10866e" strokeWidth="3" vectorEffect="non-scaling-stroke" /></svg><div className="chart-x-labels"><span>Sep 08</span><span>Sep 14</span><span>Sep 20</span><span>Sep 26</span><span>Oct 07</span></div></div>;
}

function Overview({ onNavigate, onExport }: { onNavigate: (section: Section) => void; onExport: () => void }) {
  return <>
    <PageHeading eyebrow="Tuesday, October 7, 2026" title="Good morning, Amina" description="Here’s what’s happening across your pharmacy today." actions={<><span className="range-chip"><Icon name="clock" size={16} /> Last 30 days <span className="range-chevron">⌄</span></span><button className="button-primary" onClick={onExport}><Icon name="download" size={16} /> Export report</button></>} />
    <div className="metric-grid">
      <MetricCard label="Net sales" value="EGP 48,290" change="12.8%" note="vs. previous period" icon="analytics" tone="green" />
      <MetricCard label="Gross profit" value="EGP 12,740" change="8.2%" note="vs. previous period" icon="spark" tone="violet" />
      <MetricCard label="Orders" value="1,248" change="6.4%" note="vs. previous period" icon="orders" tone="amber" />
      <MetricCard label="Inventory value" value="EGP 86,420" change="2.1%" note="vs. previous period" icon="inventory" tone="blue" />
    </div>
    <div className="overview-grid">
      <section className="panel revenue-panel"><div className="panel-heading"><div><h2>Sales performance</h2><p>Daily net sales across the selected period</p></div><button className="icon-button small-dots" aria-label="More chart options"><Icon name="dots" /></button></div><div className="chart-total"><strong>EGP 48,290</strong><span className="positive-inline">↗ 12.8%</span></div><RevenueChart /><div className="chart-legend"><span><i className="legend-dot sales-dot" /> Net sales</span><span><i className="legend-dot target-dot" /> Previous period</span></div></section>
      <section className="panel health-panel"><div className="panel-heading"><div><h2>Inventory health</h2><p>1,284 products across all locations</p></div><button className="text-action" onClick={() => onNavigate("Inventory")}>View inventory <Icon name="arrow" size={15} /></button></div><div className="health-content"><div className="donut"><div className="donut-hole"><strong>79.7%</strong><span>in good shape</span></div></div><div className="health-legend"><div><span><i className="legend-dot healthy-dot" />Healthy</span><strong>1,024</strong></div><div><span><i className="legend-dot low-dot" />Low stock</span><strong>186</strong></div><div><span><i className="legend-dot out-dot" />Out of stock</span><strong>74</strong></div></div></div><div className="health-footer"><span><span className="pulse-dot" /> Stock health is steady</span><span>Updated just now <i className="demo-mini-dot" /></span></div></section>
    </div>
    <div className="overview-grid lower-grid">
      <section className="panel table-panel"><div className="panel-heading"><div><h2>Needs attention</h2><p>Products at or below their reorder point</p></div><button className="text-action" onClick={() => onNavigate("Inventory")}>View all <Icon name="arrow" size={15} /></button></div><div className="table-scroll"><table><thead><tr><th>PRODUCT</th><th>IN STOCK</th><th>REORDER AT</th><th>STATUS</th></tr></thead><tbody>{products.filter((product) => product.status !== "Healthy").slice(0, 4).map((product) => <tr key={product.sku}><td><div className="product-cell"><span className="product-thumb">{product.name.slice(0, 1)}</span><span><strong>{product.name}</strong><small>{product.subtitle}</small></span></div></td><td><strong>{product.stock}</strong> <span className="unit-label">{product.unit}</span></td><td>{product.reorder} <span className="unit-label">{product.unit}</span></td><td><StatusPill status={product.status} /></td></tr>)}</tbody></table></div></section>
      <section className="panel expiry-panel"><div className="panel-heading"><div><h2>Expiring soon</h2><p>Batch dates within the next 60 days</p></div><button className="text-action" onClick={() => onNavigate("Inventory")}>View batches <Icon name="arrow" size={15} /></button></div><div className="expiry-summary"><span className="expiry-icon"><Icon name="clock" size={18} /></span><span><strong>12 batches</strong><small>across 8 products need review</small></span><strong className="expiry-value">EGP 4,860</strong></div><div className="expiry-list"><div><span className="expiry-product">Omeprazole 20 mg <small>Batch OM-402 · 24 units</small></span><span className="expiry-date urgent-date">Oct 18 <small>11 days</small></span></div><div><span className="expiry-product">Vitamin C 1000 mg <small>Batch VC-118 · 16 units</small></span><span className="expiry-date">Nov 02 <small>26 days</small></span></div><div><span className="expiry-product">Loratadine 10 mg <small>Batch LR-091 · 32 units</small></span><span className="expiry-date">Nov 14 <small>38 days</small></span></div></div></section>
    </div>
    <section className="copilot-strip"><div className="copilot-mark"><Icon name="spark" size={21} /></div><div className="copilot-copy"><div className="copilot-title-row"><h2>Pharma Copilot</h2><span className="preview-pill">UI preview</span></div><p>Ask about stock, sales, suppliers, or your next best action.</p><div className="suggestion-row"><button onClick={() => onNavigate("AI Copilot")}>What should I reorder?</button><button onClick={() => onNavigate("AI Copilot")}>Summarize today’s sales</button><button onClick={() => onNavigate("AI Copilot")}>Compare supplier prices</button></div></div><button className="copilot-open" onClick={() => onNavigate("AI Copilot")}>Open copilot <Icon name="arrow" size={16} /></button></section>
  </>;
}

function StatusPill({ status }: { status: string }) {
  const normalized = status.toLowerCase().replaceAll(" ", "-");
  return <span className={`status-pill status-${normalized}`}><i />{status}</span>;
}

function AnalyticsPage() {
  return <><PageHeading eyebrow="Business intelligence" title="Analytics" description="Understand performance trends across sales and inventory." actions={<span className="range-chip"><Icon name="clock" size={16} /> Last 30 days <span className="range-chevron">⌄</span></span>} /><div className="metric-grid"><MetricCard label="Net sales" value="EGP 48,290" change="12.8%" note="vs. previous period" icon="analytics" tone="green" /><MetricCard label="Gross margin" value="26.4%" change="1.8%" note="vs. previous period" icon="spark" tone="violet" /><MetricCard label="Average order" value="EGP 386.94" change="4.1%" note="vs. previous period" icon="orders" tone="amber" /><MetricCard label="Stock turnover" value="4.8×" change="0.6×" note="vs. previous period" icon="inventory" tone="blue" /></div><div className="overview-grid analytics-grid"><section className="panel revenue-panel"><div className="panel-heading"><div><h2>Sales performance</h2><p>Sample net sales by day · EGP</p></div><DemoTag /></div><div className="chart-total"><strong>EGP 48,290</strong><span className="positive-inline">↗ 12.8%</span></div><RevenueChart /></section><section className="panel category-panel"><div className="panel-heading"><div><h2>Sales by category</h2><p>Share of sample net sales</p></div></div>{[["Pain relief", "32%", "bar-green"], ["Antibiotics", "24%", "bar-blue"], ["Digestive health", "19%", "bar-violet"], ["Vitamins", "15%", "bar-amber"], ["Other", "10%", "bar-gray"]].map(([name, value, color]) => <div className="category-row" key={name}><div><span>{name}</span><strong>{value}</strong></div><div className="category-track"><i className={color} style={{ width: value }} /></div></div>)}</section></div></>;
}

function ReportsPage({ onExport }: { onExport: (reportName?: string) => void }) {
  const reports = [
    { title: "Sales summary", detail: "Revenue, order volume, and average order value", icon: "analytics" as IconName },
    { title: "Inventory snapshot", detail: "Current stock, reorder points, and valuation", icon: "inventory" as IconName },
    { title: "Expiring batches", detail: "Batch dates and stock within your selected period", icon: "clock" as IconName },
    { title: "Supplier spend", detail: "Purchases grouped by supplier and product", icon: "suppliers" as IconName },
  ];
  return <><PageHeading eyebrow="Reporting center" title="Reports" description="A clear view of your pharmacy, ready to share with your team." actions={<button className="button-primary" onClick={() => onExport("Sales summary")}><Icon name="download" size={16} /> Export sales CSV</button>} /><div className="report-note"><span className="report-note-icon"><Icon name="spark" size={18} /></span><p><strong>Reports use sample demo data.</strong> Connect a pharmacy workspace to generate reports from your own records.</p><DemoTag /></div><div className="report-grid">{reports.map((report) => <article className="panel report-card" key={report.title}><span className="report-icon"><Icon name={report.icon} size={19} /></span><h2>{report.title}</h2><p>{report.detail}</p><button className="text-action" onClick={() => onExport(report.title)}>Download sample CSV <Icon name="arrow" size={15} /></button></article>)}</div></>;
}

function CopilotPage() {
  const [prompt, setPrompt] = useState("");
  const [notice, setNotice] = useState("");
  function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (prompt.trim()) setNotice("This is a UI preview. Connect the AI service to get a grounded answer from your pharmacy data.");
  }
  const suggestions = ["What should I reorder this week?", "Which batches expire in 30 days?", "Summarize sales by category"];
  return <><PageHeading eyebrow="Pharmacy operations assistant" title="Pharma Copilot" description="Ask clear questions about your pharmacy. Answers should be grounded in your workspace data." /><div className="copilot-page-grid"><section className="panel chat-panel"><div className="chat-header"><div className="copilot-mark"><Icon name="spark" size={20} /></div><div><strong>Pharma Copilot</strong><span><i className="offline-dot" /> Preview · backend not connected</span></div><DemoTag /></div><div className="chat-content"><div className="chat-date">TODAY · SAMPLE CONVERSATION</div><div className="chat-user"><span>Can you give me a quick inventory update?</span></div><div className="chat-answer"><div className="answer-avatar"><Icon name="spark" size={15} /></div><div className="answer-body"><div className="answer-label">PHARMA COPILOT <span className="sample-badge">SAMPLE RESPONSE</span></div><p>Your sample workspace has <strong>1,284 products</strong>. <strong>186</strong> are below their reorder point, and <strong>12 batches</strong> across 8 products expire within 60 days. Those batches represent about <strong>EGP 4,860</strong> in inventory value.</p><div className="answer-source"><Icon name="reports" size={14} /> Example source: inventory summary · sample data</div></div></div><div className="chat-suggestions">{suggestions.map((item) => <button key={item} onClick={() => setPrompt(item)}>{item}<Icon name="arrow" size={14} /></button>)}</div>{notice ? <div className="preview-notice"><Icon name="clock" size={15} />{notice}</div> : null}</div><form className="chat-composer" onSubmit={onSubmit}><input value={prompt} onChange={(event) => setPrompt(event.target.value)} placeholder="Ask about stock, sales, or suppliers…" aria-label="Ask Pharma Copilot" /><button type="submit" disabled={!prompt.trim()} aria-label="Send message"><Icon name="arrow" size={17} /></button></form><p className="chat-disclaimer">Preview only. Responses shown here are examples using sample data.</p></section><aside className="copilot-side"><section className="panel copilot-info"><p className="eyebrow">HOW IT WORKS</p><h2>Answers with evidence.</h2><p>In the connected product, the copilot will use permission-checked tools and pharmacy records to answer operational questions.</p><div className="copilot-capability"><span><Icon name="check" size={15} /></span>Inventory and batch lookups</div><div className="copilot-capability"><span><Icon name="check" size={15} /></span>Sales and profit summaries</div><div className="copilot-capability"><span><Icon name="check" size={15} /></span>Supplier comparisons</div><div className="copilot-capability"><span><Icon name="check" size={15} /></span>Confirm before changing data</div></section><section className="panel safety-card"><span className="safety-shield">✳</span><h3>Built for responsible pharmacy work</h3><p>Clinical questions need authoritative sources and pharmacist oversight. Business actions require authorization and an audit trail.</p></section></aside></div></>;
}

export default function DashboardWorkspace() {
  const [activeSection, setActiveSection] = useState<Section>("Overview");
  const [search, setSearch] = useState("");
  const [mobileNavOpen, setMobileNavOpen] = useState(false);
  const [toast, setToast] = useState("");
  const [authStatus, setAuthStatus] = useState<"checking" | "ready" | "signed_out" | "unconfigured" | "error">("checking");
  const [accessToken, setAccessToken] = useState<string | null>(null);
  const [profile, setProfile] = useState<Profile | null>(null);
  const [activeOrganizationId, setActiveOrganizationId] = useState("");

  useEffect(() => {
    if (!isSupabaseConfigured()) {
      setAuthStatus("unconfigured");
      return;
    }
    let mounted = true;
    let loadedToken: string | null = null;
    const supabase = createClient();

    async function loadProfile(session: Session | null) {
      if (!mounted) return;
      if (!session) {
        loadedToken = null;
        setAccessToken(null);
        setProfile(null);
        setAuthStatus("signed_out");
        return;
      }
      if (loadedToken === session.access_token) return;
      loadedToken = session.access_token;
      setAccessToken(session.access_token);
      setAuthStatus("checking");
      try {
        const loadedProfile = await apiFetch<Profile>("/api/v1/me", session.access_token);
        if (!mounted || loadedToken !== session.access_token) return;
        setProfile(loadedProfile);
        setAuthStatus("ready");
      } catch (error) {
        if (!mounted || loadedToken !== session.access_token) return;
        setProfile(null);
        setAuthStatus(error instanceof ApiError && error.status === 401 ? "signed_out" : "error");
      }
    }

    void supabase.auth.getSession().then(({ data, error }) => {
      if (error) {
        if (mounted) setAuthStatus("error");
        return;
      }
      return loadProfile(data.session);
    }).catch(() => { if (mounted) setAuthStatus("error"); });
    const { data: { subscription } } = supabase.auth.onAuthStateChange((_event, session) => {
      queueMicrotask(() => { void loadProfile(session); });
    });
    return () => {
      mounted = false;
      subscription.unsubscribe();
    };
  }, []);

  const memberships = profile?.memberships ?? [];
  const activeMembership: Membership | null = memberships.find((item) => item.organization_id === activeOrganizationId) ?? memberships[0] ?? null;
  useEffect(() => {
    setActiveOrganizationId((current) => memberships.some((item) => item.organization_id === current)
      ? current
      : memberships[0]?.organization_id ?? "");
  }, [memberships]);
  const displayName = profile?.full_name || profile?.email?.split("@")[0] || "Guest";
  const initials = displayName.split(/\s+/).map((part) => part[0]).join("").slice(0, 2).toUpperCase();

  function exportSampleReport(reportName = "Sales summary") {
    if (reportName === "Inventory snapshot") {
      downloadCsv("pharmaintelligence-demo-inventory.csv", [["Product", "SKU", "Category", "On hand", "Reorder point", "Status"], ...products.map((product) => [product.name, product.sku, product.category, `${product.stock} ${product.unit}`, `${product.reorder} ${product.unit}`, product.status])]);
      return;
    }
    if (reportName === "Expiring batches") {
      downloadCsv("pharmaintelligence-demo-expiring-batches.csv", [["Product", "Batch", "Units", "Expires", "Sample inventory value"], ["Omeprazole 20 mg", "OM-402", "24", "2026-10-18", "EGP 1,680"], ["Vitamin C 1000 mg", "VC-118", "16", "2026-11-02", "EGP 1,120"], ["Loratadine 10 mg", "LR-091", "32", "2026-11-14", "EGP 2,060"]]);
      return;
    }
    if (reportName === "Supplier spend") {
      downloadCsv("pharmaintelligence-demo-supplier-spend.csv", [["Supplier", "Sample purchase orders", "Sample spend"], ["United Pharma", "8", "EGP 12,480"], ["EVA Pharma", "5", "EGP 7,940"], ["Rameda Distribution", "3", "EGP 4,260"]]);
      return;
    }
    downloadCsv("pharmaintelligence-demo-sales.csv", [["Order", "Customer", "Items", "Amount", "Status", "Date"], ...demoOrders.map((order) => [order.id, order.customer, order.items, order.amount, order.status, order.date])]);
  }

  function notifyDemoAction(action: string) {
    setToast(`${action} is a UI preview. Connect the backend to use this with pharmacy records.`);
  }

  return <div className="workspace-shell">
    <aside className={`sidebar ${mobileNavOpen ? "sidebar-open" : ""}`}>
      <Link className="brand-lockup" href="/" aria-label="PharmaIntelligence overview"><span className="brand-symbol"><span /><span /><span /><span /></span><span className="brand-name">pharma<span>intelligence</span></span></Link>
      <div className="workspace-picker"><span className="workspace-avatar">{activeMembership?.organization_name.slice(0, 1).toUpperCase() ?? "P"}</span><span className="workspace-label"><strong>{activeMembership?.organization_name ?? "No organization selected"}</strong><small>{activeMembership?.role.replaceAll("_", " ") ?? "Sign in to connect"}</small></span>{memberships.length > 1 ? <select className="workspace-org-select" aria-label="Active organization" value={activeMembership?.organization_id ?? ""} onChange={(event) => setActiveOrganizationId(event.target.value)}>{memberships.map((item) => <option key={item.organization_id} value={item.organization_id}>{item.organization_name}</option>)}</select> : <span className="workspace-caret">⌄</span>}</div>
      <p className="nav-caption">WORKSPACE</p><nav className="side-nav" aria-label="Main navigation">{navigation.map((item) => <button key={item.label} className={`nav-item ${activeSection === item.label ? "active" : ""}`} onClick={() => { setActiveSection(item.label); setMobileNavOpen(false); }}><Icon name={item.icon} size={18} /><span>{item.label}</span></button>)}</nav>
      <p className="nav-caption tools-caption">TOOLS</p><button className={`nav-item copilot-nav ${activeSection === "AI Copilot" ? "active" : ""}`} onClick={() => { setActiveSection("AI Copilot"); setMobileNavOpen(false); }}><Icon name="copilot" size={18} /><span>AI Copilot</span><span className="new-tag">PREVIEW</span></button>
      <div className="sidebar-bottom"><div className="help-card"><div className="help-spark"><Icon name="spark" size={17} /></div><strong>Your team, in sync.</strong><p>One calm place for pharmacy operations.</p><button onClick={() => setActiveSection("Reports")}>Explore reports <Icon name="arrow" size={14} /></button></div><button className="nav-item settings-link" onClick={() => setActiveSection("Overview")}><Icon name="settings" size={18} /><span>Settings</span></button><div className="profile-row"><span className="profile-avatar">{initials}</span><span className="profile-name"><strong>{displayName}</strong><small>{activeMembership?.role.replaceAll("_", " ") ?? "Not signed in"}</small></span><button className="profile-more" aria-label="Sign out" onClick={() => { if (isSupabaseConfigured()) void createClient().auth.signOut(); }}><Icon name="dots" size={18} /></button></div></div>
    </aside>
    <main className="main-area">
      <header className="topbar"><button className="mobile-menu icon-button" aria-label="Open navigation" onClick={() => setMobileNavOpen((open) => !open)}><Icon name="menu" /></button><div className="breadcrumbs"><span>{activeMembership?.organization_name ?? "PharmaIntelligence"}</span><Icon name="chevron" size={14} /><strong>{activeSection}</strong></div><div className="topbar-actions"><label className="global-search"><Icon name="search" size={17} /><input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Search products, orders…" aria-label="Search products and procurement records" /><kbd>⌘ K</kbd></label><button className="icon-button notification-button" aria-label="Notifications" onClick={() => notifyDemoAction("Notifications")}><Icon name="bell" size={19} /><i /></button><span className="topbar-divider" /><div className="topbar-user"><span className="profile-avatar">{initials}</span><span><strong>{displayName}</strong><small>{authStatus === "ready" ? activeMembership?.role.replaceAll("_", " ") ?? "No organization" : "Not signed in"}</small></span><span className="workspace-caret">⌄</span></div></div></header>
      <div className="content-area"><div className="demo-banner"><span className="demo-banner-icon"><Icon name="spark" size={15} /></span><span><strong>Competition demo</strong><i /> Orders, suppliers, and pharmacy batches load from the API. Overview, analytics, report exports, and Copilot still show sample data.</span><button onClick={() => setActiveSection("AI Copilot")}>Explore AI preview <Icon name="arrow" size={14} /></button></div>
        {activeSection === "Overview" ? <Overview onNavigate={setActiveSection} onExport={() => exportSampleReport()} /> : null}
        {activeSection === "Inventory" || activeSection === "Orders" || activeSection === "Suppliers" ? <ProcurementWorkspace section={activeSection} authStatus={authStatus} accessToken={accessToken} membership={activeMembership} search={search} /> : null}
        {activeSection === "Analytics" ? <AnalyticsPage /> : null}
        {activeSection === "Reports" ? <ReportsPage onExport={exportSampleReport} /> : null}
        {activeSection === "AI Copilot" ? <CopilotPage /> : null}
        <footer className="workspace-footer"><span>PharmaIntelligence <span className="footer-dot">·</span> Competition demo</span><span>Built for safer, smarter pharmacy operations</span></footer>
        {toast ? <div className="demo-toast" role="status"><Icon name="clock" size={16} /><span>{toast}</span><button onClick={() => setToast("")} aria-label="Dismiss message">×</button></div> : null}
      </div>
    </main>
  </div>;
}
