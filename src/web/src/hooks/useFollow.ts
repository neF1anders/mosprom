import { useCallback, useEffect, useRef, useState } from "react";

// прокрутка за новым
export function useFollow() {
  const threadRef = useRef<HTMLDivElement>(null);
  const following = useRef(true);
  const [away, setAway] = useState(false);
  const toBottom = useCallback((behavior: ScrollBehavior = "auto") => {
    following.current = true;
    const element = threadRef.current;
    element?.scrollTo({ top: element.scrollHeight, behavior });
  }, []);
  useEffect(() => {
    const element = threadRef.current;
    if (!element) return;
    // новое остаётся видимым
    const observer = new MutationObserver(() => {
      if (following.current) element.scrollTop = element.scrollHeight;
    });
    observer.observe(element, {
      childList: true,
      subtree: true,
      characterData: true,
      attributes: true,
      attributeFilter: ["open"],
    });
    return () => observer.disconnect();
  }, []);
  const onScroll = useCallback((event: React.UIEvent<HTMLDivElement>) => {
    const element = event.currentTarget;
    const near =
      element.scrollHeight - element.scrollTop - element.clientHeight < 80;
    following.current = near;
    setAway(!near);
  }, []);
  const follow = useCallback(() => {
    following.current = true;
  }, []);
  return { threadRef, away, toBottom, onScroll, follow };
}
