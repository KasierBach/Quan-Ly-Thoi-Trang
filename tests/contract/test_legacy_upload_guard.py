def test_legacy_public_chat_file_is_not_servable(client):
    response = client.get('/static/uploads/chat/4ba1f6a665454713b3b704d9707876d9_original.jpg')
    assert response.status_code == 404


def test_unrelated_static_image_still_serves(client):
    response = client.get('/static/images/default.jpg')
    assert response.status_code == 200
    response.close()
