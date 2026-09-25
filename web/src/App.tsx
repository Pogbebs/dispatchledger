import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import Layout from "./components/Layout";
import Customers from "./pages/Customers";
import Deliveries from "./pages/Deliveries";
import Insights from "./pages/Insights";
import Login from "./pages/Login";
import Orders from "./pages/Orders";
import { AuthProvider, useAuth } from "./auth";

function Routed() {
  const { user, loading } = useAuth();

  // Hold the render until the stored token has been checked, so a signed-in
  // user never sees the login screen flash on a refresh.
  if (loading) return null;
  if (!user) return <Login />;

  return (
    <Routes>
      <Route element={<Layout />}>
        <Route path="/orders" element={<Orders />} />
        <Route path="/deliveries" element={<Deliveries />} />
        <Route path="/customers" element={<Customers />} />
        <Route path="/insights" element={<Insights />} />
        <Route path="*" element={<Navigate to="/orders" replace />} />
      </Route>
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
