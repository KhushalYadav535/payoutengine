import { useState, useEffect, useCallback } from "react";
import { 
  Wallet, 
  ArrowUpRight, 
  Clock, 
  CheckCircle2, 
  XCircle, 
  LayoutDashboard, 
  History, 
  Building2,
  ChevronRight,
  RefreshCw,
  Search
} from "lucide-react";

const API_BASE = import.meta.env.VITE_API_URL || "http://localhost:8000";

function paise_to_inr(paise) {
  return (paise / 100).toLocaleString("en-IN", {
    style: "currency",
    currency: "INR",
    minimumFractionDigits: 2,
  });
}

function StatusBadge({ status }) {
  const styles = {
    pending:    "bg-amber-100 text-amber-700 border-amber-200 ring-amber-500/10",
    processing: "bg-blue-100 text-blue-700 border-blue-200 ring-blue-500/10",
    completed:  "bg-emerald-100 text-emerald-700 border-emerald-200 ring-emerald-500/10",
    failed:     "bg-rose-100 text-rose-700 border-rose-200 ring-rose-500/10",
  };

  const icons = {
    pending: <Clock className="w-3 h-3" />,
    processing: <RefreshCw className="w-3 h-3 animate-spin" />,
    completed: <CheckCircle2 className="w-3 h-3" />,
    failed: <XCircle className="w-3 h-3" />,
  };

  return (
    <span className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium border ring-1 ring-inset ${styles[status] || "bg-gray-100 text-gray-700 border-gray-200"}`}>
      {icons[status]}
      {status.toUpperCase()}
    </span>
  );
}

function BalanceCard({ label, amount, icon: Icon, colorClass }) {
  return (
    <div className={`relative overflow-hidden rounded-2xl border p-6 transition-all hover:shadow-lg ${colorClass}`}>
      <div className="relative z-10 flex flex-col gap-3">
        <div className="flex items-center justify-between">
          <span className="text-sm font-medium opacity-80 uppercase tracking-wider">{label}</span>
          <div className="p-2 bg-white/40 rounded-lg">
            <Icon className="w-5 h-5" />
          </div>
        </div>
        <div className="flex flex-col">
          <span className="text-3xl font-bold tracking-tight">{paise_to_inr(amount)}</span>
          <div className="mt-2 flex items-center text-xs font-medium opacity-70">
            <ArrowUpRight className="w-3 h-3 mr-1" />
            <span>Updated just now</span>
          </div>
        </div>
      </div>
      <div className="absolute -right-4 -bottom-4 opacity-10">
        <Icon size={120} />
      </div>
    </div>
  );
}

export default function App() {
  const [merchants, setMerchants] = useState([]);
  const [selectedMerchant, setSelectedMerchant] = useState(null);
  const [dashboard, setDashboard] = useState(null);
  const [payoutForm, setPayoutForm] = useState({ amount_inr: "", bank_account_id: "" });
  const [payoutStatus, setPayoutStatus] = useState(null);
  const [polling, setPolling] = useState(false);

  useEffect(() => {
    fetch(`${API_BASE}/api/v1/merchants/`)
      .then((r) => r.json())
      .then((data) => {
        setMerchants(data);
        if (data.length > 0) setSelectedMerchant(data[0].id);
      });
  }, []);

  const loadDashboard = useCallback(() => {
    if (!selectedMerchant) return;
    fetch(`${API_BASE}/api/v1/merchants/${selectedMerchant}/`)
      .then((r) => r.json())
      .then(setDashboard);
  }, [selectedMerchant]);

  useEffect(() => {
    loadDashboard();
  }, [loadDashboard]);

  useEffect(() => {
    if (!dashboard) return;
    const hasActive = dashboard.recent_payouts?.some(
      (p) => p.status === "pending" || p.status === "processing"
    );
    if (hasActive && !polling) {
      setPolling(true);
      const interval = setInterval(loadDashboard, 3000);
      return () => { clearInterval(interval); setPolling(false); };
    }
  }, [dashboard, loadDashboard, polling]);

  const handlePayoutSubmit = async (e) => {
    e.preventDefault();
    setPayoutStatus({ type: "loading", message: "Processing your request..." });
    const idempotencyKey = crypto.randomUUID();
    const amount_paise = Math.round(parseFloat(payoutForm.amount_inr) * 100);

    try {
      const res = await fetch(`${API_BASE}/api/v1/merchants/${selectedMerchant}/payouts/`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "Idempotency-Key": idempotencyKey,
        },
        body: JSON.stringify({
          amount_paise,
          bank_account_id: payoutForm.bank_account_id,
        }),
      });

      const data = await res.json();

      if (res.ok) {
        setPayoutStatus({
          type: "success",
          message: `Success! Payout of ${paise_to_inr(amount_paise)} has been initiated.`,
        });
        setPayoutForm({ amount_inr: "", bank_account_id: "" });
        loadDashboard();
        setTimeout(() => setPayoutStatus(null), 5000);
      } else {
        setPayoutStatus({
          type: "error",
          message: data.error || "Transaction failed. Please check your balance.",
        });
      }
    } catch (err) {
      setPayoutStatus({ type: "error", message: "Connection error. Please try again." });
    }
  };

  return (
    <div className="min-h-screen bg-slate-50 text-slate-900 selection:bg-indigo-100">
      {/* Navigation */}
      <nav className="sticky top-0 z-50 bg-white/80 backdrop-blur-md border-b border-slate-200">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
          <div className="flex justify-between h-16 items-center">
            <div className="flex items-center gap-3 group">
              <div className="w-10 h-10 bg-indigo-600 rounded-xl flex items-center justify-center shadow-indigo-200 shadow-lg group-hover:scale-110 transition-transform">
                <Wallet className="text-white w-6 h-6" />
              </div>
              <div>
                <h1 className="font-bold text-xl tracking-tight text-slate-900">Playto Pay</h1>
                <p className="text-[10px] font-bold uppercase tracking-[0.2em] text-indigo-500">Payout Engine</p>
              </div>
            </div>
            
            <div className="flex items-center gap-4">
              <div className="hidden sm:flex items-center gap-2 bg-slate-100 rounded-lg px-3 py-1.5 border border-slate-200">
                <Building2 className="w-4 h-4 text-slate-400" />
                <select
                  className="bg-transparent text-sm font-semibold text-slate-700 focus:outline-none min-w-[180px] cursor-pointer"
                  value={selectedMerchant || ""}
                  onChange={(e) => setSelectedMerchant(e.target.value)}
                >
                  {merchants.map((m) => (
                    <option key={m.id} value={m.id}>{m.name}</option>
                  ))}
                </select>
              </div>
            </div>
          </div>
        </div>
      </nav>

      <main className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8 space-y-8">
        {dashboard ? (
          <>
            {/* Dashboard Header */}
            <div className="flex flex-col sm:flex-row sm:items-end justify-between gap-4">
              <div>
                <h2 className="text-3xl font-extrabold text-slate-900 tracking-tight">Overview</h2>
                <p className="text-slate-500 font-medium">Real-time settlement and ledger status</p>
              </div>
              {polling && (
                <div className="inline-flex items-center gap-2 bg-indigo-50 text-indigo-600 px-3 py-1.5 rounded-full text-xs font-bold border border-indigo-100 animate-pulse">
                  <RefreshCw className="w-3 h-3" />
                  LIVE UPDATES ACTIVE
                </div>
              )}
            </div>

            {/* Statistics */}
            <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
              <BalanceCard
                label="Available to Withdraw"
                amount={dashboard.available_balance}
                icon={CheckCircle2}
                colorClass="bg-emerald-50 border-emerald-100 text-emerald-900"
              />
              <BalanceCard
                label="Locked in Processing"
                amount={dashboard.held_balance}
                icon={Clock}
                colorClass="bg-amber-50 border-amber-100 text-amber-900"
              />
              <BalanceCard
                label="Total Portfolio Value"
                amount={dashboard.total_balance}
                icon={LayoutDashboard}
                colorClass="bg-indigo-50 border-indigo-100 text-indigo-900"
              />
            </div>

            <div className="grid grid-cols-1 lg:grid-cols-3 gap-8">
              {/* Left Column: Form */}
              <div className="lg:col-span-1 space-y-6">
                <section className="bg-white rounded-2xl border border-slate-200 shadow-sm overflow-hidden">
                  <div className="p-6 border-b border-slate-100 bg-slate-50/50">
                    <h3 className="font-bold text-slate-900 flex items-center gap-2">
                      <ArrowUpRight className="w-5 h-5 text-indigo-500" />
                      New Payout
                    </h3>
                  </div>
                  <form onSubmit={handlePayoutSubmit} className="p-6 space-y-5">
                    <div className="space-y-2">
                      <label className="text-xs font-bold text-slate-500 uppercase">Amount (INR)</label>
                      <div className="relative">
                        <span className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400 font-bold">₹</span>
                        <input
                          type="number"
                          step="0.01"
                          min="1"
                          placeholder="0.00"
                          className="w-full bg-slate-50 border border-slate-200 rounded-xl pl-8 pr-4 py-3 text-lg font-bold focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500 transition-all outline-none"
                          value={payoutForm.amount_inr}
                          onChange={(e) => setPayoutForm((f) => ({ ...f, amount_inr: e.target.value }))}
                          required
                        />
                      </div>
                    </div>
                    <div className="space-y-2">
                      <label className="text-xs font-bold text-slate-500 uppercase">Destination Bank ID</label>
                      <input
                        type="text"
                        placeholder="e.g. ACC-8829-X"
                        className="w-full bg-slate-50 border border-slate-200 rounded-xl px-4 py-3 text-sm font-semibold focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500 transition-all outline-none"
                        value={payoutForm.bank_account_id}
                        onChange={(e) => setPayoutForm((f) => ({ ...f, bank_account_id: e.target.value }))}
                        required
                      />
                    </div>
                    <button
                      type="submit"
                      disabled={payoutStatus?.type === "loading"}
                      className="w-full bg-indigo-600 hover:bg-indigo-700 disabled:bg-slate-300 text-white font-bold py-4 rounded-xl shadow-lg shadow-indigo-100 transition-all flex items-center justify-center gap-2 group"
                    >
                      {payoutStatus?.type === "loading" ? (
                        <RefreshCw className="w-5 h-5 animate-spin" />
                      ) : (
                        <>
                          Send Funds
                          <ChevronRight className="w-4 h-4 group-hover:translate-x-1 transition-transform" />
                        </>
                      )}
                    </button>

                    {payoutStatus && payoutStatus.type !== "loading" && (
                      <div className={`p-4 rounded-xl flex items-start gap-3 border ${
                        payoutStatus.type === "success" ? "bg-emerald-50 border-emerald-100 text-emerald-800" : "bg-rose-50 border-rose-100 text-rose-800"
                      }`}>
                        {payoutStatus.type === "success" ? <CheckCircle2 className="w-5 h-5 shrink-0" /> : <XCircle className="w-5 h-5 shrink-0" />}
                        <p className="text-sm font-semibold leading-tight">{payoutStatus.message}</p>
                      </div>
                    )}
                  </form>
                </section>
                
                <div className="bg-indigo-900 rounded-2xl p-6 text-white shadow-xl relative overflow-hidden">
                   <div className="relative z-10">
                     <h4 className="font-bold mb-2">Need Help?</h4>
                     <p className="text-indigo-200 text-sm leading-relaxed mb-4">Payouts are typically processed within 30 seconds to our partner banks.</p>
                     <button className="text-xs font-bold bg-white/10 hover:bg-white/20 py-2 px-4 rounded-lg transition-colors">Documentation</button>
                   </div>
                   <Building2 className="absolute -right-8 -bottom-8 w-32 h-32 text-white/10" />
                </div>
              </div>

              {/* Right Column: Tables */}
              <div className="lg:col-span-2 space-y-8">
                {/* Recent Payouts */}
                <section className="bg-white rounded-2xl border border-slate-200 shadow-sm overflow-hidden">
                  <div className="px-6 py-5 border-b border-slate-100 flex items-center justify-between bg-slate-50/50">
                    <h3 className="font-bold text-slate-900 flex items-center gap-2">
                      <History className="w-5 h-5 text-indigo-500" />
                      Recent Payouts
                    </h3>
                    <div className="relative">
                      <Search className="w-4 h-4 absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" />
                      <input type="text" placeholder="Search..." className="pl-9 pr-4 py-1.5 bg-white border border-slate-200 rounded-lg text-xs outline-none focus:ring-2 focus:ring-indigo-500/20" />
                    </div>
                  </div>
                  <div className="overflow-x-auto">
                    <table className="w-full text-left">
                      <thead className="bg-slate-50/50 border-b border-slate-100">
                        <tr>
                          <th className="px-6 py-4 text-[10px] font-bold text-slate-400 uppercase tracking-widest">Transaction ID</th>
                          <th className="px-6 py-4 text-[10px] font-bold text-slate-400 uppercase tracking-widest text-right">Amount</th>
                          <th className="px-6 py-4 text-[10px] font-bold text-slate-400 uppercase tracking-widest">Status</th>
                          <th className="px-6 py-4 text-[10px] font-bold text-slate-400 uppercase tracking-widest">Completed At</th>
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-slate-100">
                        {dashboard.recent_payouts?.length === 0 ? (
                          <tr><td colSpan={4} className="px-6 py-12 text-center text-slate-400 italic">No payout activity found</td></tr>
                        ) : (
                          dashboard.recent_payouts?.map((p) => (
                            <tr key={p.id} className="hover:bg-slate-50 transition-colors group">
                              <td className="px-6 py-4 font-mono text-[10px] text-slate-500">
                                <span className="bg-slate-100 px-1.5 py-0.5 rounded uppercase">{p.id.slice(0, 8)}</span>
                                <span className="ml-2 font-semibold text-slate-400">{p.bank_account_id}</span>
                              </td>
                              <td className="px-6 py-4 text-right">
                                <span className="font-bold text-slate-900">{paise_to_inr(p.amount_paise)}</span>
                              </td>
                              <td className="px-6 py-4">
                                <StatusBadge status={p.status} />
                              </td>
                              <td className="px-6 py-4 text-xs font-medium text-slate-500">
                                {new Date(p.created_at).toLocaleDateString("en-IN", { day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit' })}
                              </td>
                            </tr>
                          ))
                        )}
                      </tbody>
                    </table>
                  </div>
                </section>

                {/* Ledger */}
                <section className="bg-white rounded-2xl border border-slate-200 shadow-sm overflow-hidden">
                  <div className="px-6 py-5 border-b border-slate-100 bg-slate-50/50">
                    <h3 className="font-bold text-slate-900 flex items-center gap-2">
                      <LayoutDashboard className="w-5 h-5 text-indigo-500" />
                      Transaction Ledger
                    </h3>
                  </div>
                  <div className="overflow-x-auto">
                    <table className="w-full text-left">
                      <thead className="bg-slate-50/50 border-b border-slate-100">
                        <tr>
                          <th className="px-6 py-4 text-[10px] font-bold text-slate-400 uppercase tracking-widest">Reference</th>
                          <th className="px-6 py-4 text-[10px] font-bold text-slate-400 uppercase tracking-widest">Type</th>
                          <th className="px-6 py-4 text-[10px] font-bold text-slate-400 uppercase tracking-widest text-right">Credit/Debit</th>
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-slate-100">
                        {dashboard.ledger?.map((txn) => (
                          <tr key={txn.id} className="hover:bg-slate-50 transition-colors">
                            <td className="px-6 py-4">
                              <div className="flex flex-col">
                                <span className="text-sm font-bold text-slate-900">{txn.description}</span>
                                <span className="text-[10px] font-mono text-slate-400 uppercase">{txn.id.slice(0, 8)}</span>
                              </div>
                            </td>
                            <td className="px-6 py-4">
                              <span className={`text-[10px] font-bold px-2 py-0.5 rounded uppercase tracking-tighter ${
                                txn.txn_type === 'credit' ? 'bg-emerald-100 text-emerald-700' : 'bg-slate-100 text-slate-600'
                              }`}>
                                {txn.txn_type}
                              </span>
                            </td>
                            <td className={`px-6 py-4 text-right font-bold ${
                              txn.txn_type === 'credit' ? 'text-emerald-600' : 'text-slate-900'
                            }`}>
                              {txn.txn_type === 'credit' ? '+' : '-'}{paise_to_inr(txn.amount_paise)}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </section>
              </div>
            </div>
          </>
        ) : (
          <div className="flex flex-col items-center justify-center py-20 space-y-4">
            <div className="w-12 h-12 border-4 border-indigo-200 border-t-indigo-600 rounded-full animate-spin"></div>
            <p className="text-slate-500 font-bold animate-pulse">Initializing Secure Engine...</p>
          </div>
        )}
      </main>
      
      <footer className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-12 text-center">
        <p className="text-slate-400 text-xs font-bold uppercase tracking-widest">
          &copy; 2026 Playto Payout Engine • Secure & Immutable Ledger
        </p>
      </footer>
    </div>
  );
}
