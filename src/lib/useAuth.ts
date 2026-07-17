// src/lib/useAuth.ts
"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { getCurrentUser, type User } from "./api";

export function useAuth() {
  const router  = useRouter();
  const [user, setUser]       = useState<User | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const u = getCurrentUser();
    if (!u) {
      router.replace("/login");
    } else {
      setUser(u);
      setLoading(false);
    }
  }, [router]);

  return { user, loading };
}