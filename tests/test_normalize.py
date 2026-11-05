from docsearch.normalize import normalize


def test_images_alerts_div():
    t = ('> [!NOTE]\n> careful\n\n> [!div class="nextstepaction"]\n> [Next](x.md)\n\n'
         ':::image type="content" source="a.png" alt-text="Portal blade" lightbox="b.png":::\n'
         ':::image type="content" source="a.png":::\n![A diagram](m/a.png) and ![](x.png)\n')
    out, _ = normalize(t)
    assert "> Note:\n> careful" in out and "[!div" not in out and "[!NOTE]" not in out
    assert "[Image: Portal blade]" in out and "[Image: A diagram] and " in out and "a.png" not in out


def test_links_rewritten_and_collected():
    m = lambda p: "https://learn.microsoft.com/azure/x/" + p.removesuffix(".md")
    out, links = normalize('See [a](b.md#h "T"), [abs](/azure/Foo/Bar/), [ext](https://x.org), [loc](#h).', m)
    assert "[a](https://learn.microsoft.com/azure/x/b#h \"T\")" in out
    assert "[abs](https://learn.microsoft.com/azure/foo/bar)" in out and "[loc](#h)" in out
    assert links == ["https://learn.microsoft.com/azure/x/b#h", "https://learn.microsoft.com/azure/foo/bar", "https://x.org"]


def test_code_untouched():
    t = "```md\n![a](b.png) [x](y.md)\n```"
    assert normalize(t)[0] == t


def test_site_rooted_links_use_the_repo_site():
    out, links = normalize("[g](/docs/reference/using-api/deprecation-guide#v1-32)", None, "https://kubernetes.io")
    assert out == "[g](https://kubernetes.io/docs/reference/using-api/deprecation-guide#v1-32)"
    assert links == ["https://kubernetes.io/docs/reference/using-api/deprecation-guide#v1-32"]
