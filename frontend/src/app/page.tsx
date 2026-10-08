import { redirect } from "next/navigation";

export default function Home() {
  // the dashboard is the landing page; it bounces to /login when signed out
  redirect("/dashboard");
}
