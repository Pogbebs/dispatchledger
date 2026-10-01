import { useCallback, useEffect, useMemo, useState, type FormEvent } from "react";
import {
  ApiError,
  api,
  type PortalOverview,
  type Product,
  type Site,
} from "../../api";
import { Pill, day, dayTime, gallons, money, price } from "../../format";

/**
 * What the customer sees: their own orders, and a form to place another.
 *
 * Nothing on this screen asks which customer. The request carries no customer
 * id, the server reads it from the token, and the database policy narrows the
 * rows before any of this code runs. The absence of a filter is the point.
 */
export default function PortalOrders() {
  const [data, setData] = useState<PortalOverview | null>(null);
  const [sites, setSites] = useState<Site[]>([]);
  const [products, setProducts] = useState<Product[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [showForm, setShowForm] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      setData(await api.portalOverview());
      setError(null);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not load your orders.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    // Only needed when the form opens, but fetched once up front so the
    // dropdowns are never empty for a moment after the first click.
    Promise.all([api.portalSites(), api.portalProducts()])
      .then(([s, p]) => {
        setSites(s);
        setProducts(p);
      })
      .catch(() => {
        // Not fatal: the order list still renders. The form reports its own
        // problem if it turns out to have nothing to offer.
      });
  }, []);

  async function cancel(id: string) {
    setBusy(id);
    try {
      await api.portalCancelOrder(id);
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not cancel that order.");
    } finally {
      setBusy(null);
    }
  }

  const summary = data?.summary;

  return (
    <>
      <div className="page-head">
        <div>
          <h1>My orders</h1>
          <div className="subtle">
            {loading ? "Loading…" : `${data?.orders.length ?? 0} shown`}
          </div>
        </div>
        <button className="btn" onClick={() => setShowForm((open) => !open)}>
          {showForm ? "Close" : "Order fuel"}
        </button>
      </div>

      {error && <div className="error">{error}</div>}

      {summary && (
        <div className="stats">
          <Stat label="Open orders" value={String(summary.open_orders)} />
          <Stat
            label="Deliveries scheduled"
            value={String(summary.scheduled_deliveries)}
          />
          <Stat label="Outstanding" value={money(summary.outstanding_total)} />
          <Stat
            label="Overdue"
            value={money(summary.overdue_total)}
            tone={Number(summary.overdue_total) > 0 ? "down" : ""}
          />
        </div>
      )}

      <div className="card">
        {showForm && (
          <OrderForm
            sites={sites}
            products={products}
            onPlaced={() => {
              setShowForm(false);
              void load();
            }}
            onError={setError}
          />
        )}

        <table>
          <thead>
            <tr>
              <th>Requested</th>
              <th>Site</th>
              <th>Product</th>
              <th className="num">Gallons</th>
              <th className="num">Unit price</th>
              <th>Status</th>
              <th>Delivery</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {data?.orders.map((row) => (
              <tr key={row.id}>
                <td className="num">{day(row.requested_date)}</td>
                <td className="truncate subtle">{row.site_address}</td>
                <td>{row.product_name}</td>
                <td className="num">{gallons(row.quantity_gal)}</td>
                <td className="num">{price(row.unit_price)}</td>
                <td>
                  <Pill status={row.status} />
                </td>
                <td className="subtle">
                  {row.delivered_at
                    ? `${dayTime(row.delivered_at)} · ${gallons(row.delivered_gal)} gal`
                    : row.scheduled_at
                      ? dayTime(row.scheduled_at)
                      : "—"}
                </td>
                <td className="cell-actions">
                  {row.status === "pending" && (
                    <button
                      className="btn btn-quiet btn-sm"
                      disabled={busy === row.id}
                      onClick={() => cancel(row.id)}
                    >
                      {busy === row.id ? "…" : "Cancel"}
                    </button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>

        {!loading && data?.orders.length === 0 && (
          <div className="empty">
            No orders yet. Use <strong>Order fuel</strong> to place your first one.
          </div>
        )}
      </div>
    </>
  );
}

function Stat({
  label,
  value,
  tone = "",
}: {
  label: string;
  value: string;
  tone?: string;
}) {
  return (
    <div className="stat">
      <div className="stat-label">{label}</div>
      <div className={`stat-value ${tone}`}>{value}</div>
    </div>
  );
}

function OrderForm({
  sites,
  products,
  onPlaced,
  onError,
}: {
  sites: Site[];
  products: Product[];
  onPlaced: () => void;
  onError: (message: string) => void;
}) {
  const tomorrow = useMemo(
    () => new Date(Date.now() + 86400000).toISOString().slice(0, 10),
    [],
  );

  const [siteId, setSiteId] = useState("");
  const [productId, setProductId] = useState("");
  const [gallonsWanted, setGallonsWanted] = useState("2000");
  const [when, setWhen] = useState(tomorrow);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!siteId && sites.length) setSiteId(sites[0].id);
    if (!productId && products.length) setProductId(products[0].id);
  }, [sites, products, siteId, productId]);

  // Shown before the order is placed, from the same list price the server
  // will snapshot. A quote the customer sees and an invoice they later
  // receive should not be the first time those two numbers meet.
  const chosen = products.find((p) => p.id === productId);
  const estimate =
    chosen && Number(gallonsWanted) > 0
      ? money(String(Number(chosen.current_price) * Number(gallonsWanted)))
      : null;

  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    try {
      await api.portalPlaceOrder({
        site_id: siteId,
        product_id: productId,
        quantity_gal: gallonsWanted,
        requested_date: when,
      });
      onPlaced();
    } catch (err) {
      onError(err instanceof ApiError ? err.message : "Could not place that order.");
    } finally {
      setBusy(false);
    }
  }

  if (!sites.length) {
    return (
      <div className="empty">
        No delivery sites are set up for your account yet. Your distributor adds
        these.
      </div>
    );
  }

  return (
    <form className="inline-panel" onSubmit={submit}>
      <label>
        Deliver to
        <select value={siteId} onChange={(e) => setSiteId(e.target.value)} required>
          {sites.map((s) => (
            <option key={s.id} value={s.id}>
              {s.address}
            </option>
          ))}
        </select>
      </label>

      <label>
        Product
        <select
          value={productId}
          onChange={(e) => setProductId(e.target.value)}
          required
        >
          {products.map((p) => (
            <option key={p.id} value={p.id}>
              {p.name} — {price(p.current_price)}/{p.unit}
            </option>
          ))}
        </select>
      </label>

      <label>
        Gallons
        <input
          type="number"
          min="1"
          step="50"
          value={gallonsWanted}
          onChange={(e) => setGallonsWanted(e.target.value)}
          required
        />
      </label>

      <label>
        Needed by
        <input
          type="date"
          value={when}
          onChange={(e) => setWhen(e.target.value)}
          required
        />
      </label>

      <div className="inline-panel-actions">
        {estimate && <span className="subtle">Estimated {estimate}</span>}
        <button className="btn" disabled={busy}>
          {busy ? "Placing…" : "Place order"}
        </button>
      </div>
    </form>
  );
}
