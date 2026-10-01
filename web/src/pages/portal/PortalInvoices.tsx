import { useCallback, useEffect, useState } from "react";
import { ApiError, api, type PortalInvoiceRow } from "../../api";
import { day, money } from "../../format";

/**
 * What the customer owes.
 *
 * Read-only, and that is a decision rather than an omission: there is no
 * endpoint behind this page that settles an invoice. A customer marking their
 * own bill paid is the first thing anyone looks for when they are handed a
 * portal, so the capability does not exist on the server either.
 */
export default function PortalInvoices() {
  const [rows, setRows] = useState<PortalInvoiceRow[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      setRows(await api.portalInvoices());
      setError(null);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not load invoices.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const unpaid = rows.filter((r) => r.status === "unpaid");
  const outstanding = unpaid.reduce((total, r) => total + Number(r.amount), 0);
  const overdue = unpaid
    .filter((r) => r.days_overdue > 0)
    .reduce((total, r) => total + Number(r.amount), 0);

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Invoices</h1>
          <div className="subtle">
            {loading ? "Loading…" : `${rows.length} shown`}
          </div>
        </div>
      </div>

      {error && <div className="error">{error}</div>}

      <div className="stats">
        <div className="stat">
          <div className="stat-label">Outstanding</div>
          <div className="stat-value">{money(String(outstanding))}</div>
        </div>
        <div className="stat">
          <div className="stat-label">Of which overdue</div>
          <div className={`stat-value ${overdue > 0 ? "down" : ""}`}>
            {money(String(overdue))}
          </div>
        </div>
      </div>

      <div className="card">
        <table>
          <thead>
            <tr>
              <th>Invoice</th>
              <th>Issued</th>
              <th>Due</th>
              <th className="num">Amount</th>
              <th>Status</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.id}>
                <td className="num">{row.invoice_number}</td>
                <td className="num">{day(row.issued_at)}</td>
                <td className="num">{day(row.due_date)}</td>
                <td className="num">{money(row.amount)}</td>
                <td>
                  {row.status === "paid" ? (
                    <span className="pill pill-delivered">Paid</span>
                  ) : row.days_overdue > 0 ? (
                    // The count comes from the server, so every client agrees
                    // on which day it is and what counts as late.
                    <span className="pill pill-pending">
                      {row.days_overdue} days overdue
                    </span>
                  ) : (
                    <span className="pill pill-scheduled">Due</span>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>

        {!loading && rows.length === 0 && (
          <div className="empty">Nothing has been invoiced to you yet.</div>
        )}
      </div>
    </>
  );
}
