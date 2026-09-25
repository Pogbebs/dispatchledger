/**
 * One place for every request to the API.
 *
 * The token is attached here, a 401 anywhere logs the user out rather than
 * leaving a half-broken screen, and the server's error detail is surfaced so
 * the UI can show what actually went wrong.
 */

const BASE = import.meta.env.VITE_API_URL ?? "/api";
const TOKEN_KEY = "dispatchledger.token";

export class ApiError extends Error {
  status: number;
  constructor(message: string, status: number) {
    super(message);
    this.status = status;
  }
}

let onUnauthorized: (() => void) | null = null;

export function setUnauthorizedHandler(handler: () => void) {
  onUnauthorized = handler;
}

export function getToken(): string | null {
  return localStorage.getItem(TOKEN_KEY);
}

export function setToken(token: string | null) {
  if (token === null) localStorage.removeItem(TOKEN_KEY);
  else localStorage.setItem(TOKEN_KEY, token);
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const token = getToken();
  const response = await fetch(`${BASE}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...init.headers,
    },
  });

  if (response.status === 401) {
    setToken(null);
    onUnauthorized?.();
    throw new ApiError("Your session has expired. Please sign in again.", 401);
  }

  if (!response.ok) {
    let detail = `Request failed (${response.status})`;
    try {
      const body = await response.json();
      if (typeof body.detail === "string") detail = body.detail;
      else if (Array.isArray(body.detail) && body.detail[0]?.msg) {
        detail = body.detail[0].msg;
      }
    } catch {
      // Non-JSON error body: keep the generic message.
    }
    throw new ApiError(detail, response.status);
  }

  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}

// ---------- types mirroring the API ----------

export interface Me {
  id: string;
  email: string;
  full_name: string;
  role: "admin" | "dispatcher" | "driver";
  tenant_id: string;
  tenant_name: string;
  tenant_slug: string;
}

export interface Customer {
  id: string;
  name: string;
  email: string | null;
  phone: string | null;
  payment_terms_days: number;
}

export interface Product {
  id: string;
  name: string;
  unit: string;
  current_price: string;
}

export interface Site {
  id: string;
  customer_id: string;
  address: string;
  tank_capacity_gal: string;
}

export interface OrderRow {
  id: string;
  customer_id: string;
  site_id: string;
  product_id: string;
  quantity_gal: string;
  unit_price: string;
  status: string;
  requested_date: string;
  customer_name: string;
  product_name: string;
  site_address: string;
}

export interface DeliveryRow {
  id: string;
  order_id: string;
  driver_id: string | null;
  scheduled_at: string;
  delivered_at: string | null;
  delivered_gal: string | null;
  status: string;
  customer_name: string;
  product_name: string;
  ordered_gal: string;
  driver_name: string | null;
}

/** Warehouse rows, not application rows. Read through the same tenant-scoped
 *  connection as everything else -- the mart carries its own row-security
 *  policy so the API never needs the analytics credential. */
export interface WeeklyPricePosition {
  week_start: string;
  delivery_count: number;
  delivered_gal: string;
  revenue: string;
  avg_price: string;
  market_price: string;
  price_delta: string;
  margin_vs_benchmark: string;
}

export interface InsightsSummary {
  weeks_covered: number;
  delivery_count: number;
  delivered_gal: string;
  revenue: string;
  avg_price: string;
  market_price: string;
  price_delta: string;
  margin_vs_benchmark: string;
  first_week: string;
  latest_week: string;
}

export interface Insights {
  /** False until dbt has built the marts: the app schema and the warehouse
   *  are created by different tools, so a fresh database has one and not the
   *  other. */
  warehouse_available: boolean;
  weeks: WeeklyPricePosition[];
  summary: InsightsSummary | null;
}

// ---------- calls ----------

export const api = {
  login: (tenant_slug: string, email: string, password: string) =>
    request<{ access_token: string }>("/login", {
      method: "POST",
      body: JSON.stringify({ tenant_slug, email, password }),
    }),

  me: () => request<Me>("/me"),

  customers: () => request<Customer[]>("/customers?limit=200"),

  products: () => request<Product[]>("/products"),

  sites: (customerId?: string) =>
    request<Site[]>(`/sites${customerId ? `?customer_id=${customerId}` : ""}`),

  orders: (status?: string) =>
    request<OrderRow[]>(`/orders?limit=100${status ? `&status=${status}` : ""}`),

  createOrder: (body: {
    customer_id: string;
    site_id: string;
    product_id: string;
    quantity_gal: string;
    requested_date: string;
  }) => request<OrderRow>("/orders", { method: "POST", body: JSON.stringify(body) }),

  cancelOrder: (id: string) =>
    request<OrderRow>(`/orders/${id}/cancel`, { method: "POST" }),

  deliveries: (status?: string) =>
    request<DeliveryRow[]>(
      `/deliveries?limit=100${status ? `&status=${status}` : ""}`,
    ),

  insights: (weeks = 26) => request<Insights>(`/insights?weeks=${weeks}`),

  completeDelivery: (id: string, delivered_gal: string) =>
    request<DeliveryRow>(`/deliveries/${id}/complete`, {
      method: "POST",
      body: JSON.stringify({ delivered_gal }),
    }),
};
