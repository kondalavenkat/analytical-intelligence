// src/app/page.tsx  —  redirect to /dashboard (auth guard handles /login redirect)
import { redirect } from "next/navigation";

export default function Home() {
  redirect("/dashboard");
}