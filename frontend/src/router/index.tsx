import { createBrowserRouter, Navigate } from "react-router-dom";

import RequireAuth from "@/components/RequireAuth";
import AppLayout from "@/layouts/AppLayout";
import LoginPage from "@/pages/LoginPage";
import NotFoundPage from "@/pages/NotFoundPage";
import SearchPage from "@/pages/SearchPage";
import TableDetailPage from "@/pages/TableDetailPage";
import TablesPage from "@/pages/TablesPage";

export const router = createBrowserRouter([
  { path: "/login", element: <LoginPage /> },
  {
    path: "/",
    element: (
      <RequireAuth>
        <AppLayout />
      </RequireAuth>
    ),
    children: [
      { index: true, element: <Navigate to="/search" replace /> },
      { path: "search", element: <SearchPage /> },
      { path: "tables", element: <TablesPage /> },
      { path: "tables/:urn", element: <TableDetailPage /> },
      { path: "*", element: <NotFoundPage /> },
    ],
  },
]);
