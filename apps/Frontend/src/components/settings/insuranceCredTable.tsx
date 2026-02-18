import React, { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { apiRequest } from "@/lib/queryClient";
import { Button } from "../ui/button";
import { Edit, Delete, Plus } from "lucide-react";
import { CredentialForm } from "./InsuranceCredForm";
import { DeleteConfirmationDialog } from "../ui/deleteDialog";

type Credential = {
  id: number;
  siteKey: string;
  username: string;
  password: string;
};

// Map site keys to friendly labels
const SITE_KEY_LABELS: Record<string, string> = {
  MH: "MassHealth",
  DDMA: "Delta Dental MA",
  DELTAINS: "Delta Dental Ins",
  DENTAQUEST: "Tufts SCO / DentaQuest",
  UNITEDSCO: "United SCO",
};

function getSiteKeyLabel(siteKey: string): string {
  return SITE_KEY_LABELS[siteKey] || siteKey;
}

export function CredentialTable() {
  const queryClient = useQueryClient();

  // Fetch current user
  const {
    data: currentUser,
    isLoading: isUserLoading,
    isError: isUserError,
  } = useQuery({
    queryKey: ["/api/users/"],
    queryFn: async () => {
      const res = await apiRequest("GET", "/api/users/");
      if (!res.ok) throw new Error("Failed to fetch user");
      return res.json();
    },
  });

  const [currentPage, setCurrentPage] = useState(1);
  const [modalOpen, setModalOpen] = useState(false);
  const [editingCred, setEditingCred] = useState<Credential | null>(null);

  const credentialsPerPage = 5;

  const { data: credentials = [], isLoading, error } = useQuery({
    queryKey: ["/api/insuranceCreds/"],
    queryFn: async () => {
      const res = await apiRequest("GET", "/api/insuranceCreds/");
      if (!res.ok) throw new Error("Failed to fetch credentials");
      return res.json() as Promise<Credential[]>;
    },
  });

  const deleteMutation = useMutation({
    mutationFn: async (cred: Credential) => {
      const res = await apiRequest("DELETE", `/api/insuranceCreds/${cred.id}`);
      if (!res.ok) throw new Error("Failed to delete credential");
      return true;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["/api/insuranceCreds/"] });
    },
  });

   // New state for delete dialog
  const [isDeleteDialogOpen, setIsDeleteDialogOpen] = useState(false);
  const [credentialToDelete, setCredentialToDelete] = useState<Credential | null>(null);

  const handleDeleteClick = (cred: Credential) => {
    setCredentialToDelete(cred);
    setIsDeleteDialogOpen(true);
  };

  const handleConfirmDelete = () => {
    if (credentialToDelete) {
      deleteMutation.mutate(credentialToDelete, {
        onSuccess: () => {
          setIsDeleteDialogOpen(false);
          setCredentialToDelete(null);
        },
      });
    }
  };

  const handleCancelDelete = () => {
    setIsDeleteDialogOpen(false);
    setCredentialToDelete(null);
  };

  const indexOfLast = currentPage * credentialsPerPage;
  const indexOfFirst = indexOfLast - credentialsPerPage;
  const currentCredentials = credentials.slice(indexOfFirst, indexOfLast);
  const totalPages = Math.ceil(credentials.length / credentialsPerPage);

  if (isUserLoading) return <p>Loading user...</p>;
  if (isUserError) return <p>Error loading user</p>;

  return (
    <div className="bg-white shadow rounded-lg overflow-hidden">
      <div className="flex justify-between items-center p-4 border-b border-gray-200">
        <h2 className="text-lg font-semibold text-gray-900">Insurance Credentials</h2>
        <Button
          onClick={() => {
            setEditingCred(null);
            setModalOpen(true);
          }}
        >
          <Plus className="mr-2 h-4 w-4" /> Add Credential
        </Button>
      </div>

      <div className="overflow-x-auto">
        <table className="min-w-full divide-y divide-gray-200">
          <thead className="bg-gray-50">
            <tr>
              <th className="px-4 py-2 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                Provider
              </th>
              <th className="px-4 py-2 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                Username
              </th>
              <th className="px-4 py-2 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                Password
              </th>
              <th className="px-4 py-2" />
            </tr>
          </thead>
          <tbody className="bg-white divide-y divide-gray-200">
            {isLoading ? (
              <tr>
                <td colSpan={4} className="text-center py-4">
                  Loading credentials...
                </td>
              </tr>
            ) : error ? (
              <tr>
                <td colSpan={4} className="text-center py-4 text-red-600">
                  Error loading credentials
                </td>
              </tr>
            ) : currentCredentials.length === 0 ? (
              <tr>
                <td colSpan={4} className="text-center py-4">
                  No credentials found.
                </td>
              </tr>
            ) : (
              currentCredentials.map((cred) => (
                <tr key={cred.id}>
                  <td className="px-4 py-2">{getSiteKeyLabel(cred.siteKey)}</td>
                  <td className="px-4 py-2">{cred.username}</td>
                  <td className="px-4 py-2">••••••••</td>
                  <td className="px-4 py-2 text-right">
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={() => {
                        setEditingCred(cred);
                        setModalOpen(true);
                      }}
                    >
                      <Edit className="h-4 w-4" />
                    </Button>
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={() => handleDeleteClick(cred)}
                    >
                      <Delete className="h-4 w-4 text-red-600" />
                    </Button>
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>

      {/* Pagination */}
      {credentials.length > credentialsPerPage && (
        <div className="bg-white px-4 py-3 flex items-center justify-between border-t border-gray-200">
          <div className="hidden sm:flex sm:flex-1 sm:items-center sm:justify-between">
            <p className="text-sm text-gray-700">
              Showing <span className="font-medium">{indexOfFirst + 1}</span> to{" "}
              <span className="font-medium">{Math.min(indexOfLast, credentials.length)}</span> of{" "}
              <span className="font-medium">{credentials.length}</span> results
            </p>

            <nav className="inline-flex -space-x-px rounded-md shadow-sm" aria-label="Pagination">
              <a
                href="#"
                onClick={(e) => { e.preventDefault(); if (currentPage > 1) setCurrentPage(currentPage - 1); }}
                className={`relative inline-flex items-center px-2 py-2 rounded-l-md border border-gray-300 bg-white text-sm font-medium text-gray-500 hover:bg-gray-50 ${currentPage === 1 ? "pointer-events-none opacity-50" : ""}`}
              >
                Previous
              </a>

              {Array.from({ length: totalPages }).map((_, i) => (
                <a
                  key={i}
                  href="#"
                  onClick={(e) => { e.preventDefault(); setCurrentPage(i + 1); }}
                  className={`relative inline-flex items-center px-4 py-2 border text-sm font-medium ${currentPage === i + 1
                    ? "z-10 bg-blue-50 border-blue-500 text-blue-600"
                    : "border-gray-300 text-gray-500 hover:bg-gray-50"}`}
                >
                  {i + 1}
                </a>
              ))}

              <a
                href="#"
                onClick={(e) => { e.preventDefault(); if (currentPage < totalPages) setCurrentPage(currentPage + 1); }}
                className={`relative inline-flex items-center px-2 py-2 rounded-r-md border border-gray-300 bg-white text-sm font-medium text-gray-500 hover:bg-gray-50 ${currentPage === totalPages ? "pointer-events-none opacity-50" : ""}`}
              >
                Next
              </a>
            </nav>
          </div>
        </div>
      )}

      {/* Modal for Add/Edit */}
      {modalOpen && currentUser && (
        <CredentialForm
          userId={currentUser.id}
          defaultValues={editingCred || undefined}
          onClose={() => setModalOpen(false)}
        />
      )}

      <DeleteConfirmationDialog
        isOpen={isDeleteDialogOpen}
        onConfirm={handleConfirmDelete}
        onCancel={handleCancelDelete}
        entityName={credentialToDelete ? getSiteKeyLabel(credentialToDelete.siteKey) : undefined}
      />
    </div>
  );
}
