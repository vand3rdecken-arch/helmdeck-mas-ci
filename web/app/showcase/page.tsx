import SkewCards from "@/components/ui/gradient-card-showcase";
import { GlassBlogCard } from "@/components/ui/glass-blog-card-shadcnui";

export default function ShowcasePage() {
  return (
    <div className="bg-[#0b0b12] min-h-screen">
      <div className="flex min-h-[70vh] items-center justify-center p-8">
        <GlassBlogCard />
      </div>
      <SkewCards />
    </div>
  );
}
