import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import Layout from "./components/Layout";
import PortalLayout from "./components/PortalLayout";
import AcceptInvite from "./pages/AcceptInvite";
import Customers from "./pages/Customers";
import Deliveries from "./pages/Deliveries";
import Insights from "./pages/Insights";
import Invoices from "./pages/Invoices";
import Login from "./pages/Login";
import Orders from "./pages/Orders";
import PortalInvoices from "./pages/portal/PortalInvoices";
import PortalOrders from "./pages/portal/PortalOrders";
import { AuthProvider, useAuth } from "./auth";

/**
 * One build, two applications.
 *
 * Staff and customers sign in through the same form and land in different
 * shells, chosen by the role in the token. The split here is for navigation
 * only -- what each side can actually read is decided by which database role
 * their requests run on, and nothing in this file could widen that.
 */
function Routed() {
  const { user, loading } = useAuth();

  // Hold the render until the stored token has been checked, so a signed-in
  // user never sees the login screen flash on a refresh.
  if (loading) return null;

  return (
    <Routes>
      {/* Reachable signed out: it is how an account comes to exist. */}
      <Route path="/invite/:token" element={<AcceptInvite />} />

      {!user ? (
        <Route path="*" element={<Login />} />
      ) : user.role === "customer" ? (
        <Route element={<PortalLayout />}>
          <Route path="/portal/orders" element={<PortalOrders />} />
          <Route path="/portal/invoices" element={<PortalInvoices />} />
          {/* A customer who types /insights lands on their own orders. The
              redirect is a courtesy; the refusal is in the database. */}
          <Route path="*" element={<Navigate to="/portal/orders" replace />} />
        </Route>
      ) : (
        <Route element={<Layout />}>
          <Route path="/orders" element={<Orders />} />
          <Route path="/deliveries" element={<Deliveries />} />
          <Route path="/customers" element={<Customers />} />
          <Route path="/invoices" element={<Invoices />} />
          <Route path="/insights" element={<Insights />} />
          <Route path="*" element={<Navigate to="/orders" replace />} />
        </Route>
      )}
    </Routes>
  );
}

export default function App() {
  return (
    <BrowserRouter>
      <AuthProvider>
        <Routed />
      </AuthProvider>
    </BrowserRouter>
  );
}
