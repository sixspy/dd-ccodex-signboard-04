window.SB_VIEWS = window.SB_VIEWS || {};
window.SB_VIEWS["playlists-view"] = {
  template: `
  <div>
    <div class="panel">
      <h2>播放清单</h2>
      <p class="lead">有序素材序列；置为可播后才能发布上屏。已上屏清单加入条目时，素材分辨率族须与目标屏幕族一致，不兼容整笔拒写。</p>
      <table>
        <thead><tr><th>编码</th><th>标题</th><th>状态</th><th>过渡</th><th>条目数</th><th>负责人</th><th></th></tr></thead>
        <tbody>
          <tr v-for="p in items" :key="p.id">
            <td>{{ p.code }}</td><td>{{ p.title }}</td><td>{{ p.status }}</td>
            <td>{{ p.transition }}</td><td>{{ p.item_count }}</td><td>{{ p.owner }}</td>
            <td><button class="ghost" type="button" @click="openDetail(p.id)">条目</button></td>
          </tr>
        </tbody>
      </table>
    </div>
    <div class="panel" v-if="detail">
      <h3>条目编排：{{ detail.playlist.code }}</h3>
      <p class="lead" v-if="detail.target_screens.length">
        目标屏幕：
        <span v-for="t in detail.target_screens" :key="t.id" class="badge" :class="t.family==='portrait'?'warn':''">
          {{ t.code }} {{ t.resolution }}·{{ t.family_label }}
        </span>
      </p>
      <p class="lead" v-else>清单尚未上屏，暂无目标屏幕族可校；发布上屏时将逐条校验。</p>
      <table>
        <thead><tr><th>序号</th><th>素材</th><th>种类</th><th>分辨率</th><th>族</th><th>兼容</th><th>停留</th></tr></thead>
        <tbody>
          <tr v-for="i in detail.items" :key="i.id">
            <td>{{ i.seq }}</td><td>{{ i.asset_code }} {{ i.asset_title }}</td><td>{{ i.kind }}</td>
            <td>{{ i.resolution }}</td><td>{{ i.family_label }}</td>
            <td>
              <span v-if="i.compatible === true" class="badge">兼容</span>
              <span v-else-if="i.compatible === false" class="badge bad">不兼容</span>
              <span v-else class="badge warn">未上屏</span>
            </td>
            <td>{{ i.dwell_sec }}s</td>
          </tr>
        </tbody>
      </table>
      <div class="row-form">
        <input v-model.number="form.asset_id" type="number" placeholder="素材ID" />
        <input v-model.number="form.seq" type="number" placeholder="序号" />
        <input v-model.number="form.dwell_sec" type="number" placeholder="停留秒" />
        <button class="primary" type="button" @click="addItem">加入条目</button>
      </div>
      <p class="err" v-if="error">{{ error }}</p>
      <p v-if="msg">{{ msg }}</p>
    </div>
  </div>`,
  data() {
    return {
      items: [],
      detail: null,
      form: { asset_id: null, seq: 1, dwell_sec: 10 },
      error: "",
      msg: ""
    };
  },
  async mounted() { await this.reload(); },
  methods: {
    async reload() { this.items = (await SB.api("/api/playlists")).items; },
    async openDetail(id) {
      this.error = ""; this.msg = "";
      this.detail = await SB.api("/api/playlists/" + id);
    },
    async addItem() {
      this.error = ""; this.msg = "";
      try {
        await SB.api("/api/playlists/" + this.detail.playlist.id + "/items", {
          method: "POST",
          body: JSON.stringify(this.form)
        });
        this.msg = "条目已入册";
        await this.openDetail(this.detail.playlist.id);
        await this.reload();
      } catch (e) { this.error = e.message; }
    }
  }
};
