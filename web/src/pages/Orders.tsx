import {
  Fragment,
  useCallback,
  useEffect,
  useMemo,
  useState,
  type FormEvent,
} from "react";
import {
  ApiError,
  api,
  type Customer,
  type Driver,
  type OrderRow,
  type Product,
  type Site,
} from "../api";
import { useAuth } from "../auth";
import { Pill, day, gallons, money, price } from "../format";

const STATUSES = ["pending", "scheduled", "delivered", "cancelled"];

/**
 * A delivery is scheduled for a morning slot. The API takes a timestamp, the
 * dispatcher thinks in days, and inventing a time-picker for a business where
 * the delivery window is "Tuesday" would be precision nobody asked for.
 */
function morningOf(date: string): string {
  return `${date}T08:00:00Z`;
}

export default function Orders() {
  const { user } = useAuth();
  const canEdit = user?.role === "admin" || user?.role === "dispatcher";

  const [rows, setRows] = useState<OrderRow[]>([]);
  const [drivers, setDrivers] = useState<Driver[]>([]);
  const [status, setStatus] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [showForm, setShowForm] = useState(false);

  // Which order is being scheduled, and the values for it.
  const [scheduling, setScheduling] = useState<string | null>(null);
  const [driverId, setDriverId] = useState("");
  const [schedDate, setSchedDate] = useState(() =>
    new Date(Date.now() + 86400000).toISOString().slice(0, 10),
  );
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      setRows(await api.orders(status || undefined));
      setError(null);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not load orders.");
    } finally {
      setLoading(false);
    }
  }, [status]);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    if (!canEdit) return;
    api.drivers().then(setDrivers).catch(() => {
      // Not fatal: scheduling still works with the delivery unassigned, and a
      // failed dropdown should not take the whole board down.
    });
  }, [canEdit]);

  async function cancel(id: string) {
    try {
      await api.cancelOrder(id);
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not cancel.");
    }
  }

  async function schedule(orderId: string) {
    setBusy(true);
    try {
      await api.scheduleDelivery({
        order_id: orderId,
        driver_id: driverId || null,
        scheduled_at: morningOf(schedDate),
      });
      setScheduling(null);
      await load();
    } catch (err) {
      setError(
        err instanceof ApiError ? err.message : "Could not schedule the delivery.",
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Orders</h1>
          <div className="subtle">
            {loading ? "Loading…" : `${rows.length} shown`}
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
          {canEdit && (
            <button className="btn" onClick={() => setShowForm((open) => !open)}>
              {showForm ? "Close" : "New order"}
            </button>
          )}
        </div>
      </div>

      {error && <div className="error">{error}</div>}

      <div className="card">
        {showForm && canEdit && (
          <NewOrderForm
            onCreated={() => {
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
              <th>Customer</th>
              <th>Site</th>
              <th>Product</th>
              <th className="num">Gallons</th>
              <th className="num">Unit price</th>
              <th className="num">Value</th>
              <th>Status</th>
              {canEdit && <th />}
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <Fragment key={row.id}>
              <tr>
                <td className="num">{day(row.requested_date)}</td>
                <td>{row.customer_name}</td>
                <td className="truncate subtle">{row.site_address}</td>
                <td>{row.product_name}</td>
                <td className="num">{gallons(row.quantity_gal)}</td>
                <td className="num">{price(row.unit_price)}</td>
                <td className="num">
                  {money(
                    String(Number(row.quantity_gal) * Number(row.unit_price)),
                  )}
                </td>
                <td>
                  <Pill status={row.status} />
                </td>
                {canEdit && (
                  <td className="cell-actions">
                    <span className="inline-form">
                      {row.status === "pending" && (
                        <button
                          className="btn btn-sm"
                          onClick={() =>
                            setScheduling(scheduling === row.id ? null : row.id)
                          }
                        >
                          Schedule
                        </button>
                      )}
                      {row.status !== "delivered" &&
                        row.status !== "cancelled" && (
                          <button
                            className="btn btn-quiet btn-sm"
                            onClick={() => cancel(row.id)}
                          >
                            Cancel
                          </button>
                        )}
                    </span>
                  </td>
                )}
              </tr>

              {/* The scheduling controls are a select, a date and two buttons.
                  Put in the actions cell they widen the whole table and push
                  the buttons off the right edge, so they get a row of their
                  own directly beneath the order they belong to. */}
              {canEdit && scheduling === row.id && (
                <tr className="sched-row">
                  <td colSpan={9}>
                    <div className="sched-form">
                      <span className="sched-label">
                        Schedule {gallons(row.quantity_gal)} gal of{" "}
                        {row.product_name} for {row.customer_name}
                      </span>
                      <label>
                        Driver
                        <select
                          value={driverId}
                          onChange={(e) => setDriverId(e.target.value)}
                        >
                          <option value="">Unassigned</option>
                          {drivers.map((d) => (
                            <option key={d.id} value={d.id}>
                              {d.full_name}
                            </option>
                          ))}
                        </select>
                      </label>
                      <label>
                        Date
                        <input
                          type="date"
                          value={schedDate}
                          onChange={(e) => setSchedDate(e.target.value)}
                        />
                      </label>
                      <button
                        className="btn btn-sm"
                        disabled={busy}
                        onClick={() => schedule(row.id)}
                      >
                        {busy ? "…" : "Confirm"}
                      </button>
                      <button
                        className="btn btn-quiet btn-sm"
                        onClick={() => setScheduling(null)}
                      >
                        Cancel
                      </button>
                    </div>
                  </td>
                </tr>
              )}
              </Fragment>
            ))}
          </tbody>
        </table>

        {!loading && rows.length === 0 && (
          <div className="empty">No orders match this filter.</div>
        )}
      </div>
    </>
  );
}

function NewOrderForm({
  onCreated,
  onError,
}: {
  onCreated: () => void;
  onError: (message: string) => void;
}) {
  const [customers, setCustomers] = useState<Customer[]>([]);
  const [products, setProducts] = useState<Product[]>([]);
  const [sites, setSites] = useState<Site[]>([]);

  const [customerId, setCustomerId] = useState("");
  const [siteId, setSiteId] = useState("");
  const [productId, setProductId] = useState("");
  const [quantity, setQuantity] = useState("1000");
  const [date, setDate] = useState(() => new Date().toISOString().slice(0, 10));
  const [busy, setBusy] = useState(false);

  // Adding a customer mid-order, rather than abandoning the order and coming
  // back. A first delivery to a new customer is exactly when an order gets
  // typed in, so requiring the customer to exist first gets the sequence
  // backwards.
  const [addingCustomer, setAddingCustomer] = useState(false);
  const [newName, setNewName] = useState("");
  const [newTerms, setNewTerms] = useState("30");
  const [newAddress, setNewAddress] = useState("");
  const [newCapacity, setNewCapacity] = useState("5000");

  const loadCustomers = useCallback(async () => {
    const list = await api.customers();
    setCustomers(list);
    return list;
  }, []);

  useEffect(() => {
    Promise.all([loadCustomers(), api.products()])
      .then(([c, p]) => {
        setProducts(p);
        if (c[0]) setCustomerId(c[0].id);
        if (p[0]) setProductId(p[0].id);
      })
      .catch(() => onError("Could not load the order form."));
  }, [loadCustomers, onError]);

  // Sites belong to a customer, so the list reloads whenever it changes.
  useEffect(() => {
    if (!customerId) return;
    api
      .sites(customerId)
      .then((list) => {
        setSites(list);
        setSiteId(list[0]?.id ?? "");
      })
      .catch(() => onError("Could not load delivery sites."));
  }, [customerId, onError]);

  const selectedProduct = useMemo(
    () => products.find((p) => p.id === productId),
    [products, productId],
  );

  async function createCustomer(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    try {
      // Two calls, in order: a site needs a customer to belong to. If the
      // second fails the customer still exists, which is recoverable -- the
      // dispatcher adds the site and carries on -- where a half-created site
      // pointing at nothing would not be.
      const customer = await api.createCustomer({
        name: newName,
        payment_terms_days: Number(newTerms),
      });
      await api.createSite({
        customer_id: customer.id,
        address: newAddress,
        tank_capacity_gal: Number(newCapacity).toFixed(2),
      });

      await loadCustomers();
      setCustomerId(customer.id);
      setAddingCustomer(false);
      setNewName("");
      setNewAddress("");
    } catch (err) {
      onError(
        err instanceof ApiError ? err.message : "Could not add the customer.",
      );
    } finally {
      setBusy(false);
    }
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    try {
      await api.createOrder({
        customer_id: customerId,
        site_id: siteId,
        product_id: productId,
        quantity_gal: Number(quantity).toFixed(2),
        requested_date: date,
      });
      onCreated();
    } catch (err) {
      onError(
        err instanceof ApiError ? err.message : "Could not create the order.",
      );
    } finally {
      setBusy(false);
    }
  }

  if (addingCustomer) {
    return (
      <form className="form-grid" onSubmit={createCustomer}>
        <div>
          <label htmlFor="cname">Customer name</label>
          <input
            id="cname"
            value={newName}
            onChange={(e) => setNewName(e.target.value)}
            required
            autoFocus
          />
        </div>

        <div>
          <label htmlFor="cterms">Payment terms (days)</label>
          <input
            id="cterms"
            type="number"
            min="0"
            max="120"
            value={newTerms}
            onChange={(e) => setNewTerms(e.target.value)}
            required
          />
        </div>

        <div>
          <label htmlFor="caddr">First delivery site</label>
          <input
            id="caddr"
            value={newAddress}
            onChange={(e) => setNewAddress(e.target.value)}
            required
          />
        </div>

        <div>
          <label htmlFor="ccap">Tank capacity (gal)</label>
          <input
            id="ccap"
            type="number"
            min="1"
            value={newCapacity}
            onChange={(e) => setNewCapacity(e.target.value)}
            required
          />
        </div>

        <button className="btn" disabled={busy}>
          {busy ? "Adding…" : "Add customer"}
        </button>
        <button
          type="button"
          className="btn btn-quiet"
          onClick={() => setAddingCustomer(false)}
        >
          Back
        </button>
      </form>
    );
  }

  return (
    <form className="form-grid" onSubmit={submit}>
      <div>
        <label htmlFor="customer">Customer</label>
        <select
          id="customer"
          value={customerId}
          onChange={(e) => {
            if (e.target.value === "__new") setAddingCustomer(true);
            else setCustomerId(e.target.value);
          }}
        >
          {customers.map((c) => (
            <option key={c.id} value={c.id}>
              {c.name}
            </option>
          ))}
          <option value="__new">+ New customer…</option>
        </select>
      </div>

      <div>
        <label htmlFor="site">Delivery site</label>
        <select
          id="site"
          value={siteId}
          onChange={(e) => setSiteId(e.target.value)}
        >
          {sites.map((s) => (
            <option key={s.id} value={s.id}>
              {s.address}
            </option>
          ))}
        </select>
      </div>

      <div>
        <label htmlFor="product">Product</label>
        <select
          id="product"
          value={productId}
          onChange={(e) => setProductId(e.target.value)}
        >
          {products.map((p) => (
            <option key={p.id} value={p.id}>
              {p.name}
            </option>
          ))}
        </select>
      </div>

      <div>
        <label htmlFor="qty">
          Gallons
          {selectedProduct && (
            <span style={{ textTransform: "none", fontWeight: 400 }}>
              {" "}
              at {price(selectedProduct.current_price)}
            </span>
          )}
        </label>
        <input
          id="qty"
          type="number"
          min="1"
          step="1"
          value={quantity}
          onChange={(e) => setQuantity(e.target.value)}
          required
        />
      </div>

      <div>
        <label htmlFor="date">Requested date</label>
        <input
          id="date"
          type="date"
          value={date}
          onChange={(e) => setDate(e.target.value)}
          required
        />
      </div>

      <button className="btn" disabled={busy || !siteId}>
        {busy ? "Creating…" : "Create order"}
      </button>
    </form>
  );
}
