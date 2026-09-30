import { useCallback, useEffect, useState } from "react";
import { ApiError, api, type Invoices as InvoicesData } from "../api";
import { useAuth } from "../auth";
import { day, gallons, money } from "../format";

/**
 * Receivables: what was billed, what is owed, what is late.
 *
 * Every completed delivery has written an invoice since the first day of this
 * project, and until now none of them appeared anywhere in the application.
 * An operations system that bills customers and cannot show you a bill is
 * missing the half that pays for the trucks.
 */

const STATUSES = ["unpaid", "paid", "void"];

/** Days overdue into the buckets a finance team actually uses. */
function ageing(days: number): { label: string; tone: string } {
  if (days <= 0) return { label: "Current", tone: "" };
  if (days <= 30) return { label: "1–30 days", tone: "warn" };
  if (days <= 60) return { label: "31–60 days", tone: "warn" };
  if (days <= 90) return { label: "61–90 days", tone: "down" };
  return { label: "90+ days", tone: "down" };
}

export default function Invoices() {
  const { user } = useAuth();
  const canEdit = user?.role === "admin" || user?.role === "dispatcher";

  const [data, setData] = useState<InvoicesData | null>(null);
  const [status, setStatus] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [paying, setPaying] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      setData(await api.invoices(status || undefined));
      setError(null);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not load invoices.");
    } finally {
      setLoading(false);
    }
  }, [status]);

  useEffect(() => {
    void load();
  }, [load]);

  async function pay(id: string) {
    setPaying(id);
    try {
      await api.payInvoice(id);
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not record payment.");
    } finally {
      setPaying(null);
    }
  }

  const summary = data?.summary;

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Invoices</h1>
          <div className="subtle">
            {loading ? "Loading…" : `${data?.rows.length ?? 0} shown`}
          </div>
        </div>
        <div className="filters">
          <select value={status} onChange={(e) => setStatus(e.target.value)}>
            <option value="">All statuses</option>
            {STATUSES.map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </select>
        </div>
      </div>

      {error && <div className="error">{error}</div>}

      {/* The summary covers every invoice, not the filtered page: what you are
          owed is a fact about the business, not about the current filter. */}
      {summary && (
        <div className="stats">
          <div className="stat">
            <div className="stat-label">Outstanding</div>
            <div className="stat-value">{money(summary.outstanding_total)}</div>
            <div className="stat-note">
              across {summary.outstanding_count} unpaid invoices
            </div>
          </div>

          <div className="stat">
            <div className="stat-label">Overdue</div>
            <div className={`stat-value ${summary.overdue_count > 0 ? "down" : ""}`}>
              {money(summary.overdue_total)}
            </div>
            <div className="stat-note">
              {summary.overdue_count} past their due date
            </div>
          </div>

          <div className="stat">
            <div className="stat-label">Collected</div>
            <div className="stat-value up">{money(summary.paid_total)}</div>
            <div className="stat-note">{summary.paid_count} invoices paid</div>
          </div>
        </div>
      )}

      <div className="card">
        <table>
          <thead>
            <tr>
              <th>Invoice</th>
              <th>Customer</th>
              <th className="num">Issued</th>
              <th className="num">Due</th>
              <th className="num">Gallons</th>
              <th className="num">Amount</th>
              <th>Status</th>
              {canEdit && <th />}
            </tr>
          </thead>
          <tbody>
            {data?.rows.map((row) => {
              const age = ageing(row.days_overdue);
              return (
                <tr key={row.id}>
                  <td className="num">{row.invoice_number}</td>
                  <td>{row.customer_name}</td>
                  <td className="num subtle">{day(row.issued_at)}</td>
                  <td className="num">{day(row.due_date)}</td>
                  <td className="num">{gallons(row.delivered_gal)}</td>
                  <td className="num">{money(row.amount)}</td>
                  <td>
                    {row.status === "paid" ? (
                      <span className="pill pill-completed">paid</span>
                    ) : row.status === "void" ? (
                      <span className="pill">void</span>
                    ) : (
                      <span className={`pill pill-${row.days_overdue > 0 ? "failed" : "scheduled"}`}>
                        {age.label}
                      </span>
                    )}
                  </td>
                  {canEdit && (
                    <td className="cell-actions">
                      {row.status === "unpaid" && (
                        <button
                          className="btn btn-quiet btn-sm"
                          disabled={paying === row.id}
                          onClick={() => pay(row.id)}
                        >
                          {paying === row.id ? "Saving…" : "Mark paid"}
                        </button>
                      )}
                    </td>
                  )}
                </tr>
              );
            })}
          </tbody>
        </table>

        {!loading && data?.rows.length === 0 && (
          <div className="empty">No invoices match this filter.</div>
        )}
      </div>

      <p className="subtle footnote">
        Invoices are raised automatically when a delivery is completed, for the
        gallons that actually arrived rather than the gallons ordered. The due
        date comes from the customer's payment terms.
      </p>
    </>
  );
}
