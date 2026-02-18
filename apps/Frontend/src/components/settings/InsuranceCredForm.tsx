import { useEffect, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { apiRequest } from "@/lib/queryClient";
import { toast } from "@/hooks/use-toast";

type CredentialFormProps = {
  onClose: () => void;
  userId: number;
  defaultValues?: {
    id?: number;
    siteKey: string;
    username: string;
    password: string;
  };
};

// Available site keys - must match exactly what the automation buttons expect
const SITE_KEY_OPTIONS = [
  { value: "MH", label: "MassHealth" },
  { value: "DDMA", label: "Delta Dental MA" },
  { value: "DELTAINS", label: "Delta Dental Ins" },
  { value: "DENTAQUEST", label: "Tufts SCO / DentaQuest" },
  { value: "UNITEDSCO", label: "United SCO" },
];

export function CredentialForm({ onClose, userId, defaultValues }: CredentialFormProps) {
  const [siteKey, setSiteKey] = useState(defaultValues?.siteKey || "");
  const [username, setUsername] = useState(defaultValues?.username || "");
  const [password, setPassword] = useState(defaultValues?.password || "");

  const queryClient = useQueryClient();

  // Create or Update Mutation inside form
  const mutation = useMutation({
    mutationFn: async () => {
      const payload = {
        siteKey: siteKey.trim(),
        username: username.trim(),
        password: password.trim(),
        userId,
      };

      const url = defaultValues?.id
        ? `/api/insuranceCreds/${defaultValues.id}`
        : "/api/insuranceCreds/";

      const method = defaultValues?.id ? "PUT" : "POST";

      const res = await apiRequest(method, url, payload);

      if (!res.ok) {
        const errorData = await res.json().catch(() => null);
        throw new Error(errorData?.message || "Failed to save credential");
      }
      return res.json();
    },
    onSuccess: () => {
      toast({
        title: `Credential ${defaultValues?.id ? "updated" : "created"}.`,
      });
      queryClient.invalidateQueries({ queryKey: ["/api/insuranceCreds/"] });
      onClose();
    },
    onError: (error: any) => {
      toast({
        title: "Error",
        description: error.message || "Unknown error",
        variant: "destructive",
      });
    },
  });

  // Reset form on defaultValues change (edit mode)
  useEffect(() => {
    setSiteKey(defaultValues?.siteKey || "");
    setUsername(defaultValues?.username || "");
    setPassword(defaultValues?.password || "");
  }, [defaultValues]);

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();

    if (!siteKey || !username || !password) {
      toast({
        title: "Error",
        description: "All fields are required.",
        variant: "destructive",
      });
      return;
    }

    mutation.mutate();
  };

  return (
    <div className="fixed inset-0 bg-black bg-opacity-50 flex justify-center items-center z-50">
      <div className="bg-white rounded-lg p-6 w-full max-w-md shadow-lg">
        <h2 className="text-lg font-bold mb-4">
          {defaultValues?.id ? "Edit Credential" : "Create Credential"}
        </h2>
        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label className="block text-sm font-medium">Insurance Provider</label>
            <select
              value={siteKey}
              onChange={(e) => setSiteKey(e.target.value)}
              className="mt-1 p-2 border rounded w-full bg-white"
            >
              <option value="">Select a provider...</option>
              {SITE_KEY_OPTIONS.map((opt) => (
                <option key={opt.value} value={opt.value}>
                  {opt.label}
                </option>
              ))}
            </select>
          </div>
          <div>
            <label className="block text-sm font-medium">Username</label>
            <input
              type="text"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              className="mt-1 p-2 border rounded w-full"
            />
          </div>
          <div>
            <label className="block text-sm font-medium">Password</label>
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="mt-1 p-2 border rounded w-full"
            />
          </div>
          <div className="flex justify-end gap-2">
            <button
              type="button"
              onClick={onClose}
              className="text-gray-600 hover:underline"
              disabled={mutation.isPending}
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={mutation.isPending}
              className="bg-blue-600 text-white px-4 py-2 rounded hover:bg-blue-700 disabled:opacity-50"
            >
              {mutation.isPending
                ? defaultValues?.id
                  ? "Updating..."
                  : "Creating..."
                : defaultValues?.id
                ? "Update"
                : "Create"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
