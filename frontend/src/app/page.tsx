import { redirect } from "next/navigation";

export default function Home() {
  // the chatbot is the main interface; /ask bounces to /login when signed out
  redirect("/ask");
}
