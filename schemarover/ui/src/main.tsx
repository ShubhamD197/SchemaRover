import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import Ask from "./Ask";
import Admin from "./Admin";
import Login from "./Login";
import { getToken } from "./api";
import "./index.css";

/** No session token → login page. An expired token is caught by api.ts on the first 401. */
const Private = ({ children }: { children: React.ReactNode }) =>
  getToken() ? children : <Navigate to="/login" replace />;

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <BrowserRouter>
      <Routes>
        <Route path="/login" element={<Login />} />
        <Route path="/" element={<Private><Ask /></Private>} />
        <Route path="/admin" element={<Private><Admin /></Private>} />
      </Routes>
    </BrowserRouter>
  </StrictMode>
);
