export type Status = "confirmed" | "needs_review";
export type Box = { x: number; y: number; width: number; height: number };
export type Edition = {
  id: string;
  year: number | null;
  volume: string | null;
  pages: number;
  people: number;
};
export type PersonSummary = {
  id: string;
  occurrenceId: string;
  pageId: string;
  pageName: string;
  name: string;
  status: Status;
  gender: string;
  generation: number | null;
  bbox: Box | null;
};
export type PageSummary = { id: string; name: string; people: number };
export type PageDetail = PageSummary & {
  edition: string;
  peopleList: PersonSummary[];
  image: {
    url: string;
    width: number;
    height: number;
    offsetX: number;
    offsetY: number;
    isRoi: boolean;
  } | null;
};
export type PersonDetail = {
  id: string;
  sources: (PersonSummary & {
    informationStatus: Status;
    fields: Record<string, string | number | null>;
    rawName: string;
  })[];
  partners: {
    kind: string;
    status: Status;
    name: string;
    personId: string | null;
  }[];
};
export type Relative = PersonSummary & { kind: string; edgeId: string };
export type Listing<T> = { items: T[]; hasMore: boolean; nextOffset: number };
